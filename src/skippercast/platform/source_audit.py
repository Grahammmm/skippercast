"""Bounded documentation-access audit. HTTP success is not scientific approval."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import ipaddress
import socket
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from .contracts import REPO, atomic_json, load_catalogs, public_url, stamp


def check_public_address(url):
    public_url(url)
    addresses = socket.getaddrinfo(urlsplit(url).hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Source resolved to a non-public address")


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public_address(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def probe(source):
    url=source["documentation_url"]
    row={"source_id":source["id"],"url":url,"checked_at":stamp(),"source_issue_time":None,
         "scope":"documentation access only; no automatic change to coverage or review status"}
    try:
        check_public_address(url)
        request=Request(url,headers={"User-Agent":"SkipperCast research (https://skippercast.com)","Accept":"text/html,application/json,text/plain,*/*"})
        with build_opener(PublicRedirect()).open(request,timeout=18) as r:
            body=r.read(1_000_001)
            row.update(status="accessible",http_status=r.status,final_url=r.url,
                       content_type=r.headers.get("Content-Type"),http_last_modified=r.headers.get("Last-Modified"),
                       sampled_bytes=len(body),body_complete=len(body)<=1_000_000,sha256=hashlib.sha256(body).hexdigest())
            if not body.strip(): raise ValueError("Empty documentation response")
    except Exception as e:
        row.update(status="unavailable",error=f"{type(e).__name__}: {str(e)[:180]}")
    return row


def audit(root=REPO):
    _, sources=load_catalogs(root)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(probe,sources.values()))
    return {"schema_version":1,"checked_at":stamp(),"sources":rows,
            "note":"Checks document access and receipts only. Dataset rights, variables, coverage and suitability remain reviewed separately. Retrieval and HTTP modification dates are not scientific issue times."}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",required=True)
    result=audit();atomic_json(p.parse_args().output,result)
    print({"checked":len(result["sources"]),"accessible":sum(s["status"]=="accessible" for s in result["sources"])})
