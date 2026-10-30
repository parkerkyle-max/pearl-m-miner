"""Validate static project pages, or verify their deployed HTTP responses.

This checks crawlability signals, not search indexing, rankings or real bot visits.
"""
import argparse
import datetime
from html.parser import HTMLParser
import json
import hashlib
import math
from pathlib import Path
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
BASE='https://parkerkyle-max.github.io/pearl-m-miner/'
PAGES=['','zh/','ja/','ko/','faq/','about/','privacy/']
if (ROOT/'docs/data/m2-validation-20261030.json').exists():PAGES.append('m2/')
class Page(HTMLParser):
    def __init__(self):
        super().__init__();self.lang=None;self.h1=0;self.title=0;self.canonical=None;self.alternates={};self.links=[];self.meta={};self.schema=[];self.in_schema=False;self.schema_text='';self.text=[];self.device_families=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='html':self.lang=a.get('lang')
        if tag=='h1':self.h1+=1
        if tag=='details' and 'device-family' in a.get('class','').split():self.device_families.append(a.get('id'))
        if tag=='title':self.title+=1
        if tag=='link' and a.get('rel')=='canonical':self.canonical=a.get('href')
        if tag=='link' and a.get('rel')=='alternate' and a.get('hreflang'):self.alternates[a['hreflang']]=a.get('href')
        if tag in ('a','link') and a.get('href'):self.links.append(a['href'])
        if tag=='img' and a.get('src'):self.links.append(a['src'])
        if tag=='meta':self.meta[a.get('name',a.get('property',''))]=a.get('content','')
        if tag=='script' and a.get('type')=='application/ld+json':self.in_schema=True;self.schema_text=''
    def handle_data(self,data):
        if self.in_schema:self.schema_text+=data
        else:self.text.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.in_schema:
            self.schema.append(json.loads(self.schema_text));self.in_schema=False

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--live',action='store_true');ap.add_argument('--output',type=Path);a=ap.parse_args()
    report={'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'mode':'live' if a.live else 'local','target':BASE,'checks':[], 'scope':'HTTP/content checks; no indexing, ranking, real crawler or revenue claim'}
    def read(path,user_agent='Pearl-M-Miner-Docs-Check/1.0'):
        if not a.live:return (ROOT/'docs'/path).read_bytes(),{}
        url=BASE+path
        if path.endswith('index.html'):url=url[:-10]
        request=urllib.request.Request(url,headers={'User-Agent':user_agent})
        with urllib.request.urlopen(request,timeout=25) as response:
            assert response.status==200,(url,response.status)
            assert 'noindex' not in response.headers.get('X-Robots-Tag','').lower(),url
            raw=response.read()
            local=ROOT/'docs'/path
            assert raw==local.read_bytes(),('Deployed content differs',path)
            return raw,dict(response.headers)
    # Guard the public comparison data independently of the rendered percentages.
    from build_device_matrix import validate, render
    device_body,_=read('device-results.json');devices=json.loads(device_body)
    validate(devices)
    for result in devices['results'].values():
        comparison=result['comparison']
        ratio=comparison['candidate_mean_ths']/comparison['baseline_mean_ths']
        assert math.isclose((ratio-1)*100,comparison['improvement_percent'],abs_tol=0.03),result['chip']
        if 'ratio' in comparison:assert math.isclose(ratio,comparison['ratio'],abs_tol=0.005),result['chip']
    for template in ('device-result.yml','benchmark-discrepancy.yml'):
        assert (ROOT/'.github/ISSUE_TEMPLATE'/template).is_file(),template
    css,_=read('site-assets/site.css');assert b'.device-family' in css and b'.matrix-feedback' in css
    for slug in PAGES:
        body,headers=read(slug+'index.html');p=Page();p.feed(body.decode('utf-8'))
        assert p.lang and p.h1==1 and p.title==1 and p.canonical==BASE+slug,slug
        assert len(' '.join(p.text))>500 and p.meta.get('description') and p.meta.get('og:image'),slug
        assert p.schema and 'noindex' not in p.meta.get('robots','').lower(),slug
        assert all('aggregateRating' not in s for s in p.schema),'No unverified ratings'
        assert p.meta.get('og:url')==p.canonical,slug
        if slug in ('','zh/','ja/','ko/'):
            assert p.alternates=={'en':BASE,'zh-CN':BASE+'zh/','ja':BASE+'ja/','ko':BASE+'ko/','x-default':BASE},slug
            assert p.device_families==[f'device-m{i}' for i in range(1,7)],(slug,p.device_families)
            assert render(devices,{'':'en','zh/':'zh','ja/':'ja','ko/':'ko'}[slug]) in body.decode('utf-8'),('Stale device matrix',slug)
            assert all(any('template='+name in url for url in p.links) for name in ('device-result.yml','benchmark-discrepancy.yml')),slug
        for link in p.links:
            target=urllib.parse.urljoin(BASE+slug,link)
            if target.startswith(BASE):
                relative=urllib.parse.urlsplit(target).path[len(urllib.parse.urlsplit(BASE).path):]
                if not relative or relative.endswith('/'):relative+='index.html'
                assert (ROOT/'docs'/urllib.parse.unquote(relative)).is_file(),('Broken project link',slug,link)
        report['checks'].append({'path':slug or '/','bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'lang':p.lang,'raw_html':True,'canonical':p.canonical,'structured_data':True})
    sitemap,_=read('sitemap.xml');tree=ET.fromstring(sitemap)
    locations={n.text for n in tree.findall('{*}url/{*}loc')}
    assert locations=={BASE+s for s in PAGES},locations
    guide,_=read('llms.txt');assert b'When to use' in guide and b'--dev-fee 0' in guide
    manifest,_=read('miner-manifest.json');m=json.loads(manifest)
    assert m['repository']=='https://github.com/parkerkyle-max/pearl-m-miner'
    assert m['developer_contribution']['optional'] and not m['operation']['starts_mining']
    social,_=read('site-assets/social.png');assert social.startswith(b'\x89PNG\r\n\x1a\n')
    if a.live:
        probes=[]
        for agent in ['Googlebot','bingbot','OAI-SearchBot','PerplexityBot']:
            body,_=read('index.html',agent);assert b'<h1>' in body
            probes.append({'user_agent':agent,'http_success':True})
        report['user_agent_response_checks']=probes
        try:
            urllib.request.urlopen(BASE+'does-not-exist-docs-check',timeout=15)
            raise AssertionError('Expected HTTP 404')
        except urllib.error.HTTPError as error:assert error.code==404
        report['missing_page_http_404']=True
    report['passed']=True
    if a.output:a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
