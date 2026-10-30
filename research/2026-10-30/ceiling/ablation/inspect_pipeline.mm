// Compile-time metadata only. No command queue, command buffer or GPU dispatch.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <CommonCrypto/CommonDigest.h>
#include <cstdio>

static int fail(NSString *message, NSError *error = nil) {
    NSString *detail = error ? [message stringByAppendingFormat:@": %@", error.localizedDescription] : message;
    fprintf(stderr, "%s\n", detail.UTF8String);
    return 1;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return fail(@"Usage: inspect_pipeline /path/to/prefix.metal");
        if (@available(macOS 26.0, *)) {
            NSString *path = [NSString stringWithUTF8String:argv[1]];
            NSData *bytes = [NSData dataWithContentsOfFile:path];
            if (!bytes || !bytes.length || bytes.length >= (4u << 20))
                return fail(@"Shader must be a readable UTF-8 file smaller than 4 MiB");
            NSString *source = [[NSString alloc] initWithData:bytes encoding:NSUTF8StringEncoding];
            if (!source) return fail(@"Shader is not valid UTF-8");

            unsigned char digest[CC_SHA256_DIGEST_LENGTH];
            CC_SHA256(bytes.bytes, static_cast<CC_LONG>(bytes.length), digest);
            const char *hex = "0123456789abcdef";
            char sha[CC_SHA256_DIGEST_LENGTH * 2 + 1];
            for (unsigned i = 0; i < CC_SHA256_DIGEST_LENGTH; ++i) {
                sha[i * 2] = hex[digest[i] >> 4];
                sha[i * 2 + 1] = hex[digest[i] & 15];
            }
            sha[sizeof(sha) - 1] = '\0';

            id<MTLDevice> device = MTLCreateSystemDefaultDevice();
            if (!device) device = MTLCopyAllDevices().firstObject;
            if (!device) return fail(@"Metal device unavailable");
            MTLCompileOptions *options = [MTLCompileOptions new];
            options.languageVersion = MTLLanguageVersion4_0;
            options.mathMode = MTLMathModeSafe;
            NSError *error = nil;
            id<MTLLibrary> library = [device newLibraryWithSource:source options:options error:&error];
            if (!library) return fail(@"Shader compilation failed", error);
            id<MTLFunction> function = [library newFunctionWithName:@"prefix_pair"];
            if (!function) return fail(@"prefix_pair not found");
            id<MTLComputePipelineState> pipeline = [device newComputePipelineStateWithFunction:function error:&error];
            if (!pipeline) return fail(@"prefix_pair pipeline creation failed", error);

            NSDictionary *result = @{
                @"kind": @"PIPELINE_METADATA_ONLY",
                @"device": device.name,
                @"shader_path": path,
                @"shader_sha256": [NSString stringWithUTF8String:sha],
                @"entry_point": @"prefix_pair",
                @"metal_language": @"4.0",
                @"math_mode": @"safe",
                @"threadExecutionWidth": @(pipeline.threadExecutionWidth),
                @"maxTotalThreadsPerThreadgroup": @(pipeline.maxTotalThreadsPerThreadgroup),
                @"staticThreadgroupMemoryLength": @(pipeline.staticThreadgroupMemoryLength),
                @"deviceMaxThreadgroupMemoryLength": @(device.maxThreadgroupMemoryLength),
                @"gpu_dispatch_performed": @NO,
                @"actual_occupancy": [NSNull null],
                @"register_count": [NSNull null]
            };
            NSData *json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:&error];
            if (!json) return fail(@"JSON serialization failed", error);
            fwrite(json.bytes, 1, json.length, stdout);
            fputc('\n', stdout);
            return 0;
        }
        return fail(@"Requires macOS 26+ and an SDK with Metal 4");
    }
}
