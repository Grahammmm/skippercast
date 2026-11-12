"""Bounded documentation-access audit. HTTP success is not scientific approval."""
import argparse
from concurrent.futures import ThreadPoolExecutor

from .. import http
from .contracts import REPO, atomic_json, load_catalogs, public_url, stamp

SAMPLE_BYTES = 1_000_000


def probe(source, session=None):
    url=source["documentation_url"]
    row={"source_id":source["id"],"url":url,"checked_at":stamp(),"source_issue_time":None,
         "scope":"documentation access only; no automatic change to coverage or review status"}
    try:
        public_url(url)
        # Documentation pages may redirect to any public host (DOI resolvers do);
        # private and loopback addresses stay refused. Only a sample is read.
        r=(session or http.default_session()).get(
            url,headers={"Accept":"text/html,application/json,text/plain,*/*"},timeout=18,
            max_bytes=SAMPLE_BYTES,truncate=True,allowed_hosts=["*"],use_cache=False)
        body=r.body
        row.update(status="accessible",http_status=r.status,final_url=r.final_url,
                   content_type=r.headers.get("Content-Type"),http_last_modified=r.headers.get("Last-Modified"),
                   sampled_bytes=len(body),body_complete=len(body)<=SAMPLE_BYTES,sha256=r.receipt.sha256)
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
