"""Invoke private trip checks with GitHub's short-lived workflow identity."""
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main():
    deployment=json.loads(Path('deployments/production.json').read_text())
    url=deployment['public_origin']+'/api/jobs/check'
    # Identify the scheduled API client explicitly; the hosting edge rejects
    # Python's generic urllib identity before requests reach the Worker.
    client='SkipperCast-trip-monitor/0.3 (+'+deployment['public_origin']+')'
    request_url=os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']+'&'+urlencode({'audience':url})
    # Neither identity token is logged or stored on disk.
    with urlopen(Request(request_url,headers={'Authorization':'Bearer '+os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN'],'User-Agent':client}),timeout=20) as response:
        token=json.load(response)['value']
    cursor=None;totals={k:0 for k in ('checked','changes','delivered','held','in_app')}
    for _ in range(100):
        request=Request(url,data=json.dumps({'cursor':cursor}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','User-Agent':client},method='POST')
        with urlopen(request,timeout=55) as response:result=json.load(response)
        for key in totals:totals[key]+=result[key]
        cursor=result['next_cursor']
        if not cursor:break
    else:raise RuntimeError('Trip batch limit reached; remaining work was not checked')
    print(json.dumps(totals))
    with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as file:file.write('\n## Private trip monitoring\n'+json.dumps(totals)+'\n')
    if totals['held']:raise RuntimeError('Delivery was held or ambiguous; receipts require reconciliation before a resend')


if __name__=='__main__':main()
