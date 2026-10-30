#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <CommonCrypto/CommonDigest.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

using Clock=std::chrono::steady_clock;
static double elapsed(Clock::time_point start){return std::chrono::duration<double>(Clock::now()-start).count();}
static uint64_t unix_ns(){return uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count());}
static void require(bool value,const std::string &why){if(!value)throw std::runtime_error(why);}
static NSString *ns(const std::string &s){return [NSString stringWithUTF8String:s.c_str()];}
static std::string sha(NSData *data){
  require(data!=nil,"missing hash input");unsigned char digest[CC_SHA256_DIGEST_LENGTH];
  CC_SHA256(data.bytes,(CC_LONG)data.length,digest);char result[65];
  for(unsigned i=0;i<32;++i)snprintf(result+2*i,3,"%02x",digest[i]);return result;
}
static void emit(const char *prefix,NSDictionary *record){
  NSError *error=nil;NSData *data=[NSJSONSerialization dataWithJSONObject:record options:0 error:&error];
  require(data!=nil,"JSON serialization failed");std::cout<<prefix<<" "<<std::string((const char*)data.bytes,data.length)<<std::endl;
}
struct Options {
  std::string mode="half",shader="peak.metal",output;
  double seconds=30,warmup=10,target_ms=20,max_ms=250;
  uint32_t groups=1024,simdgroups=4,chains=4,iterations=0;
  bool groups_set=false,chains_set=false,verify_only=false;
};
static uint32_t uint_argument(const std::string &value){
  require(!value.empty()&&value.find_first_not_of("0123456789")==std::string::npos,"unsigned integer argument required");
  const auto parsed=std::stoull(value);require(parsed<=UINT32_MAX,"integer argument overflow");return uint32_t(parsed);
}
static Options parse(int argc,char **argv){
  Options o;
  for(int i=1;i<argc;++i){std::string key=argv[i];
    if(key=="--verify-only"){o.verify_only=true;continue;}
    require(i+1<argc,"missing argument for "+key);std::string value=argv[++i];
    if(key=="--mode")o.mode=value;else if(key=="--shader")o.shader=value;else if(key=="--output")o.output=value;
    else if(key=="--seconds")o.seconds=std::stod(value);else if(key=="--warmup")o.warmup=std::stod(value);
    else if(key=="--target-ms")o.target_ms=std::stod(value);else if(key=="--max-ms")o.max_ms=std::stod(value);
    else if(key=="--groups"){o.groups=uint_argument(value);o.groups_set=true;}
    else if(key=="--simdgroups")o.simdgroups=uint_argument(value);
    else if(key=="--chains"){o.chains=uint_argument(value);o.chains_set=true;}
    else if(key=="--iterations")o.iterations=uint_argument(value);
    else throw std::runtime_error("unknown argument "+key);
  }
  require(o.mode=="half"||o.mode=="float"||o.mode=="mpp","mode must be half, float or mpp");
  if(o.mode=="mpp"){if(!o.groups_set)o.groups=64;require(o.simdgroups==4,"MPP uses exactly four SIMDgroups");require(!o.chains_set||o.chains==1,"MPP uses one accumulator chain");o.chains=1;}
  require(o.groups>=1&&o.groups<=(o.mode=="mpp"?1024u:16384u),"groups out of range");
  require(o.simdgroups==1||o.simdgroups==2||o.simdgroups==4||o.simdgroups==8,"SIMDgroups must be1,2,4,8");
  require(o.chains==1||o.chains==2||o.chains==4||o.chains==8,"chains must be1,2,4,8");
  require(std::isfinite(o.seconds)&&o.seconds>=1&&o.seconds<=3600,"seconds out of range");
  require(std::isfinite(o.warmup)&&o.warmup>=0&&o.warmup<=600,"warmup out of range");
  require(std::isfinite(o.target_ms)&&o.target_ms>=1&&o.target_ms<=100,"target-ms out of range");
  require(std::isfinite(o.max_ms)&&o.max_ms>=o.target_ms&&o.max_ms<=250,"max-ms out of range");
  require(o.iterations<=32768,"iterations must not exceed32768");return o;
}
struct Engine {
  Options o;uint32_t rows,k,sets,chains;size_t acount,bcount,ocount;
  id<MTLDevice> device;id<MTLCommandQueue> queue;id<MTLComputePipelineState> pipeline;
  id<MTLBuffer> a,b,c;std::vector<int32_t> ia,ib;std::vector<int64_t> dots,absolute;
  uint64_t macs_per_iteration;std::string shader_sha;double compile_seconds;
  static int small(uint32_t x){
    x^=x>>16;x*=0x7feb352du;x^=x>>15;x*=0x846ca68bu;x^=x>>16;
    static const int values[4]={-2,-1,1,2};return values[x&3u];
  }
  Engine(const Options &options):o(options){
    if(@available(macOS 26.0,*)){}else{throw std::runtime_error("requires macOS26+");}
    device=MTLCreateSystemDefaultDevice();require(device&&device.hasUnifiedMemory,"Apple Silicon unified-memory GPU required");
    queue=[device newCommandQueue];require(queue!=nil,"command queue failed");
    NSData *source=[NSData dataWithContentsOfFile:ns(o.shader)];require(source!=nil,"cannot read shader");shader_sha=sha(source);
    NSString *text=[[NSString alloc]initWithData:source encoding:NSUTF8StringEncoding];require(text!=nil,"shader is not UTF8");
    MTLCompileOptions *opts=[MTLCompileOptions new];opts.languageVersion=MTLLanguageVersion4_0;opts.mathMode=MTLMathModeSafe;
    opts.preprocessorMacros=@{@"BENCH_CHAINS":@(o.chains)};
    NSError *error=nil;auto start=Clock::now();
    id<MTLLibrary> library=[device newLibraryWithSource:text options:opts error:&error];
    require(library!=nil,error?error.localizedDescription.UTF8String:"shader compilation failed");
    id<MTLFunction> function=[library newFunctionWithName:ns("peak_"+o.mode)];require(function!=nil,"missing kernel");
    pipeline=[device newComputePipelineStateWithFunction:function error:&error];
    require(pipeline!=nil,error?error.localizedDescription.UTF8String:"pipeline failed");compile_seconds=elapsed(start);
    require(pipeline.threadExecutionWidth==32&&pipeline.maxTotalThreadsPerThreadgroup>=o.simdgroups*32,"unsupported threadgroup");
    rows=o.mode=="mpp"?64:8;k=o.mode=="mpp"?128:8;sets=o.mode=="mpp"?o.groups:o.groups*o.simdgroups;chains=o.chains;
    acount=size_t(sets)*rows*k;bcount=acount*chains;ocount=size_t(sets)*chains*rows*rows;
    ia.resize(acount);ib.resize(bcount);dots.resize(ocount);absolute.resize(ocount);
    const size_t input_size=o.mode=="float"?4:2;
    a=[device newBufferWithLength:acount*input_size options:MTLResourceStorageModeShared];
    b=[device newBufferWithLength:bcount*input_size options:MTLResourceStorageModeShared];
    c=[device newBufferWithLength:ocount*4 options:MTLResourceStorageModeShared];
    require(a&&b&&c,"buffer allocation failed");macs_per_iteration=uint64_t(sets)*chains*rows*rows*k;
  }
  void fill(unsigned fixture){
    for(uint32_t s=0;s<sets;++s)for(uint32_t r=0;r<rows;++r)for(uint32_t q=0;q<k;++q){
      int value=small(r*65537u+q*257u+s*17u+0xa531u);
      if(fixture==1)value=63;if(fixture==2||fixture==3)value=127;if(fixture==4)value=64;
      if(fixture==3&&((r+q+s)&1))value=-value;
      ia[(size_t(s)*rows+r)*k+q]=value;
    }
    for(uint32_t s=0;s<sets;++s)for(uint32_t chain=0;chain<chains;++chain)for(uint32_t r=0;r<rows;++r)for(uint32_t q=0;q<k;++q){
      int value=small(r*4099u+q*65537u+s*31u+chain*4093u+0x3719u);
      if(fixture==1)value=63;if(fixture==2||fixture==3)value=127;if(fixture==4)value=64;
      if(fixture==3&&((r+q+chain)&1))value=-value;
      ib[((size_t(s)*chains+chain)*rows+r)*k+q]=value;
    }
    if(o.mode=="float"){
      auto ap=(float*)a.contents,bp=(float*)b.contents;
      for(size_t i=0;i<acount;++i)ap[i]=(float)ia[i];for(size_t i=0;i<bcount;++i)bp[i]=(float)ib[i];
    }else{
      static_assert(sizeof(_Float16)==2,"host half layout");auto ap=(_Float16*)a.contents,bp=(_Float16*)b.contents;
      for(size_t i=0;i<acount;++i)ap[i]=(_Float16)ia[i];for(size_t i=0;i<bcount;++i)bp[i]=(_Float16)ib[i];
    }
    for(uint32_t s=0;s<sets;++s)for(uint32_t chain=0;chain<chains;++chain)for(uint32_t r=0;r<rows;++r)for(uint32_t col=0;col<rows;++col){
      int64_t value=0,absvalue=0;
      for(uint32_t q=0;q<k;++q){int64_t product=int64_t(ia[(size_t(s)*rows+r)*k+q])*ib[((size_t(s)*chains+chain)*rows+col)*k+q];value+=product;absvalue+=std::abs(product);}
      size_t index=((size_t(s)*chains+chain)*rows+r)*rows+col;dots[index]=value;absolute[index]=absvalue;
    }
    std::fill_n((float*)c.contents,ocount,std::numeric_limits<float>::quiet_NaN());
  }
  struct Sample {double gpu,wall;};
  Sample dispatch(uint32_t iterations){
    require(iterations>=1&&iterations<=32768,"iteration bounds");
    int state=(int)NSProcessInfo.processInfo.thermalState;require(state==0||state==1,"thermal pressure high or unavailable");
    const uint32_t params[2]={iterations,o.simdgroups};auto start=Clock::now();
    @autoreleasepool {
      id<MTLCommandBuffer> buffer=[queue commandBuffer];require(buffer!=nil,"command allocation");
      id<MTLComputeCommandEncoder> encoder=[buffer computeCommandEncoder];require(encoder!=nil,"encoder allocation");
      [encoder setComputePipelineState:pipeline];[encoder setBuffer:a offset:0 atIndex:0];[encoder setBuffer:b offset:0 atIndex:1];
      [encoder setBuffer:c offset:0 atIndex:2];[encoder setBytes:params length:sizeof(params) atIndex:3];
      [encoder dispatchThreadgroups:MTLSizeMake(o.groups,1,1) threadsPerThreadgroup:MTLSizeMake(o.simdgroups*32,1,1)];
      [encoder endEncoding];[buffer commit];[buffer waitUntilCompleted];
      require(buffer.status==MTLCommandBufferStatusCompleted,buffer.error?buffer.error.localizedDescription.UTF8String:"GPU failure");
      const double gpu=buffer.GPUEndTime-buffer.GPUStartTime,wall=elapsed(start);
      require(std::isfinite(gpu)&&gpu>0&&std::isfinite(wall)&&wall>0,"invalid GPU/host duration");
      require(gpu*1000<=o.max_ms,"observed dispatch exceeded max-ms; reduce groups/iterations");
      return {gpu,wall};
    }
  }
  void verify(uint32_t iterations){
    const auto values=(const float*)c.contents;
    for(size_t i=0;i<ocount;++i){
      require(absolute[i]*iterations<=(1ll<<24),"oracle absolute-sum bound exceeds2^24");
      require(std::isfinite(values[i])&&double(values[i])==double(dots[i]*iterations),"exact integer output mismatch at index"+std::to_string(i));
    }
  }
};

int main(int argc,char **argv){@autoreleasepool{try{
  const auto launched=Clock::now();Options o=parse(argc,argv);Engine e(o);NSMutableArray *checks=[NSMutableArray array];
  const char *fixtures[]={"runtime_small_integers","63x63_product3969","127x127_product16129","mixed_sign127","exact_2pow24_boundary"};
  for(unsigned fixture=0;fixture<5;++fixture){
    e.fill(fixture);uint32_t iterations=fixture==0?7:fixture==1?3:fixture==4?((1u<<24)/(e.k*4096u)):((1u<<24)/(e.k*16129u));
    auto sample=e.dispatch(iterations);e.verify(iterations);
    [checks addObject:@{@"fixture":ns(fixtures[fixture]),@"iterations":@(iterations),@"outputs_checked":@(e.ocount),@"gpu_seconds":@(sample.gpu),@"all_exact":@YES}];
  }
  e.fill(0);NSMutableArray *calibration=[NSMutableArray array];uint32_t iterations=o.iterations?o.iterations:1;
  while(true){auto sample=e.dispatch(iterations);e.verify(iterations);
    [calibration addObject:@{@"iterations":@(iterations),@"gpu_seconds":@(sample.gpu),@"wall_seconds":@(sample.wall)}];
    if(o.iterations||sample.gpu*1000>=o.target_ms||iterations>=32768||sample.gpu*2000>o.max_ms*.75)break;
    iterations=std::min(32768u,iterations*2);
  }
  double warmup_wall=0,gpu_seconds=0,dispatch_wall=0,max_gpu=0,measured_wall=0;uint64_t dispatches=0,total_macs=0,measure_start_ns=0,measure_end_ns=0;
  NSMutableArray *windows=[NSMutableArray array];
  if(!o.verify_only){
    auto warm=Clock::now();while(elapsed(warm)<o.warmup)e.dispatch(iterations);warmup_wall=elapsed(warm);e.verify(iterations);
    auto start=Clock::now();measure_start_ns=unix_ns();double next_check=10,window_start=0,window_gpu=0;uint64_t window_macs=0;
    while(elapsed(start)<o.seconds){auto sample=e.dispatch(iterations);
      uint64_t macs=e.macs_per_iteration*iterations;total_macs+=macs;++dispatches;gpu_seconds+=sample.gpu;dispatch_wall+=sample.wall;
      window_macs+=macs;window_gpu+=sample.gpu;max_gpu=std::max(max_gpu,sample.gpu);
      double now=elapsed(start);
      if(now>=next_check){e.verify(iterations);now=elapsed(start);
        NSDictionary *row=@{@"end_seconds":@(now),@"window_seconds":@(now-window_start),@"macs":@(window_macs),@"gpu_seconds":@(window_gpu),
          @"gpu_tflops":@(2.0*window_macs/window_gpu/1e12),@"wall_tflops":@(2.0*window_macs/(now-window_start)/1e12),@"all_outputs_exact":@YES};
        [windows addObject:row];emit("PEAK_PROGRESS",row);window_start=now;window_macs=0;window_gpu=0;next_check=now+10;
      }
    }
    measured_wall=elapsed(start);measure_end_ns=unix_ns();e.verify(iterations);
    if(window_macs){NSDictionary *row=@{@"end_seconds":@(measured_wall),@"window_seconds":@(measured_wall-window_start),@"macs":@(window_macs),@"gpu_seconds":@(window_gpu),
      @"gpu_tflops":@(2.0*window_macs/window_gpu/1e12),@"wall_tflops":@(2.0*window_macs/(measured_wall-window_start)/1e12),@"all_outputs_exact":@YES};[windows addObject:row];}
  }
  NSData *executable=[NSData dataWithContentsOfFile:ns(argv[0])];
  NSMutableDictionary *result=[@{@"schema":@"m1-matrix-peak-v1",@"mode":ns(o.mode),@"device":e.device.name,
    @"os":NSProcessInfo.processInfo.operatingSystemVersionString,@"shader_sha256":ns(e.shader_sha),@"executable_sha256":ns(sha(executable)),
    @"groups":@(o.groups),@"simdgroups_per_group":@(o.simdgroups),@"independent_chains":@(o.chains),@"threads_per_group":@(o.simdgroups*32),
    @"pipeline_max_threads":@(e.pipeline.maxTotalThreadsPerThreadgroup),@"pipeline_static_threadgroup_bytes":@(e.pipeline.staticThreadgroupMemoryLength),
    @"m":@(e.rows),@"n":@(e.rows),@"k":@(e.k),@"iterations_per_dispatch":@(iterations),@"macs_per_iteration_all_groups":@(e.macs_per_iteration),
    @"flops_per_mac":@2,@"compile_seconds":@(e.compile_seconds),@"correctness_checks":checks,@"calibration":calibration,
    @"warmup_seconds_actual":@(warmup_wall),@"measured_seconds":@(measured_wall),@"measure_start_unix_ns":@(measure_start_ns),@"measure_end_unix_ns":@(measure_end_ns),
    @"completed_dispatches":@(dispatches),@"completed_macs":@(total_macs),
    @"gpu_seconds_total":@(gpu_seconds),@"dispatch_wall_seconds_total":@(dispatch_wall),@"max_observed_gpu_dispatch_ms":@(max_gpu*1000),
    @"windows":windows,@"wall_rate_includes_periodic_verification":@YES,@"output_values_checked_per_verification":@(e.ocount),
    @"initial_input_buffer_bytes":@(e.a.length+e.b.length),@"output_bytes_per_dispatch":@(e.c.length),@"thermal_guard":@"public macOS thermal pressure; parent must additionally supervise temperature and power",
    @"inner_loop_memory":o.mode=="mpp"?@"device-backed operand tensors reread each iteration; cache residency not measured":@"matrix inputs loaded before inner loop; accumulators observed by full output store; compiler spills not measured",
    @"correctness_scope":@"tested integer fixtures with conservative absolute-sum bounds <=2^24; not proof for every legal Pearl input",
    @"scope":@"synthetic matrix arithmetic only; excludes Pearl noise, transcript, hash, proof, pool and income",
    @"total_process_seconds":@(elapsed(launched)),@"verify_only":@(o.verify_only)} mutableCopy];
  result[@"gpu_tflops"]=gpu_seconds?@(2.0*total_macs/gpu_seconds/1e12):(id)[NSNull null];
  result[@"wall_tflops"]=measured_wall?@(2.0*total_macs/measured_wall/1e12):(id)[NSNull null];
  result[@"gpu_tmacs"]=gpu_seconds?@(total_macs/gpu_seconds/1e12):(id)[NSNull null];
  if(!o.output.empty()){
    NSError *error=nil;NSData *data=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:&error];
    require(data&&[data writeToFile:ns(o.output) options:NSDataWritingAtomic error:&error],"cannot save result");
    require([data isEqualToData:[NSData dataWithContentsOfFile:ns(o.output)]],"result reread differs");
  }
  emit("PEAK_RESULT",result);return 0;
}catch(const std::exception &error){emit("PEAK_ERROR",@{@"error":ns(error.what()),@"qualified":@NO});return 2;}}}
