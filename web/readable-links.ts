const PUBLIC_STATE=['region','coast','view','target','hour','profile','day','layers','area','base','spot','focus','presentation','habitat','ui','place','mode','species'] as const;
/** Preserve public selection only; optional account or arbitrary query fields stay out. */
export function readableReportURL(href:string):URL {
 const input=new URL(href),output=new URL('/report',input.origin);
 for(const key of PUBLIC_STATE)for(const value of input.searchParams.getAll(key))output.searchParams.append(key,value);
 return output;
}
