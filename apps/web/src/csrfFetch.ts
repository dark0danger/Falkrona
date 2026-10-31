// Another Falkrona tab can rotate the shared session token during a long image job.
// Retry only an explicit CSRF rejection: the API rejects it before doing any work.
let tokenRefresh:Promise<string|null>|null=null;
async function refreshToken():Promise<string|null> {
  // Concurrent rejected requests share one rotation, so retries cannot
  // invalidate each other's fresh CSRF token.
  if(!tokenRefresh) tokenRefresh=(async()=>{
    const refreshed=await fetch("/api/v1/session/csrf",{credentials:"include"});
    if(!refreshed.ok)return null;
    const token=await refreshed.json();
    return typeof token.csrf_token==="string"&&token.csrf_token?token.csrf_token:null;
  })().finally(()=>{tokenRefresh=null;});
  return tokenRefresh;
}
export async function csrfFetch(path:string, options:RequestInit):Promise<Response> {
  const response=await fetch(path,options);
  if(response.status!==403 || !new Headers(options.headers).has("X-CSRF-Token"))return response;
  const rejected=await response.clone().json().catch(()=>null);
  if(rejected?.detail?.code!=="csrf_rejected")return response;
  const token=await refreshToken();
  if(!token)return response;
  const headers=new Headers(options.headers);headers.set("X-CSRF-Token",token);
  return fetch(path,{...options,headers});
}
