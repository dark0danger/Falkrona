// Another Falkrona tab can rotate the shared session token during a long image job.
// Retry only an explicit CSRF rejection: the API rejects it before doing any work.
export async function csrfFetch(path:string, options:RequestInit):Promise<Response> {
  const response=await fetch(path,options);
  if(response.status!==403 || !new Headers(options.headers).has("X-CSRF-Token"))return response;
  const rejected=await response.clone().json().catch(()=>null);
  if(rejected?.detail?.code!=="csrf_rejected")return response;
  const refreshed=await fetch("/api/v1/session/csrf",{credentials:"include"});
  if(!refreshed.ok)return response;
  const token=await refreshed.json();
  if(typeof token.csrf_token!=="string" || !token.csrf_token)return response;
  const headers=new Headers(options.headers);headers.set("X-CSRF-Token",token.csrf_token);
  return fetch(path,{...options,headers});
}
