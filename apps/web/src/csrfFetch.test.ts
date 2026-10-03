import {afterEach,expect,it,vi} from "vitest";
import {csrfFetch} from "./csrfFetch";
afterEach(()=>vi.unstubAllGlobals());
it("renews a rejected session token and retries the same image import once",async()=>{
  const body=new FormData();body.set("file",new Blob(["image"]),"ad.png");
  const fetchMock=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({detail:{code:"csrf_rejected"}}),{status:403}))
    .mockResolvedValueOnce(new Response(JSON.stringify({csrf_token:"fresh"})))
    .mockResolvedValueOnce(new Response("{}"));vi.stubGlobal("fetch",fetchMock);
  expect((await csrfFetch("/import",{method:"POST",credentials:"include",headers:{"X-CSRF-Token":"old"},body})).ok).toBe(true);
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(fetchMock.mock.calls[2][0]).toBe("/import");
  expect(fetchMock.mock.calls[2][1].body).toBe(body);
  expect(fetchMock.mock.calls[2][1].headers.get("X-CSRF-Token")).toBe("fresh");
});
it.each([403,500])("never retries an uncertain operation or ordinary permission failure (%s)",async(status)=>{
  const fetchMock=vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:{code:"workspace_forbidden"}}),{status}));vi.stubGlobal("fetch",fetchMock);
  expect((await csrfFetch("/import",{method:"POST",headers:{"X-CSRF-Token":"old"}})).status).toBe(status);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
