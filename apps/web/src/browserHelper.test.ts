import {afterEach, expect, it, vi} from "vitest";
import {checkImageConnection, helperRequest} from "./browserHelper";

function browser(result:unknown, origin="https://falkrona.example") {
  const listeners = new Set<(event:unknown)=>void>();
  const fake = {setTimeout,clearTimeout,
    addEventListener:(_name:string,listener:(event:unknown)=>void)=>listeners.add(listener),
    removeEventListener:(_name:string,listener:(event:unknown)=>void)=>listeners.delete(listener),
    postMessage:vi.fn((message:{id:string})=>queueMicrotask(()=>{
      for(const listener of listeners) listener({source:fake,origin,data:{channel:"falkrona-helper-response",id:message.id,result}});
    }))};
  vi.stubGlobal("window",fake);vi.stubGlobal("location",{origin:"https://falkrona.example"});
  return {fake,listeners};
}
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});
it("checks a compatible connected image provider before drafting",async()=>{
  browser({connected:true,provider:"chatgpt",helper_version:"0.1.10"});
  expect((await checkImageConnection("chatgpt")).connected).toBe(true);
});
it("requires each provider's minimum compatible helper",async()=>{
  browser({connected:true,provider:"chatgpt",helper_version:"0.1.9"});
  await expect(checkImageConnection("chatgpt")).rejects.toThrow(/0\.1\.10/);
  browser({connected:true,provider:"gemini",helper_version:"0.1.8"});
  await expect(checkImageConnection("gemini")).rejects.toThrow(/0\.1\.9/);
  browser({connected:true,provider:"gemini",helper_version:"0.1.9"});
  expect((await checkImageConnection("gemini")).connected).toBe(true);
});
it.each([
  [{connected:false},/Connect your image app/],
  [{connected:true,provider:"gemini",helper_version:"0.1.7"},/connected to Gemini/],
  [{connected:true,provider:"chatgpt",helper_version:"0.1.1"},/Update Falkrona/],
])("blocks missing, wrong, or obsolete connections",async(value,pattern)=>{
  browser(value);await expect(checkImageConnection("chatgpt")).rejects.toThrow(pattern as RegExp);
});
it("ignores cross-origin responses and cleans up after a timeout",async()=>{
  vi.useFakeTimers();const {listeners}=browser({connected:true},"https://untrusted.example");
  const result=expect(helperRequest("status")).rejects.toThrow(/connection isn’t ready/);
  await vi.advanceTimersByTimeAsync(8000);await result;expect(listeners.size).toBe(0);
});
it("opens only the specified saved request through the helper",async()=>{
  const {fake,listeners}=browser({stage:"paused"});
  await helperRequest("open",undefined,"saved-run");
  expect(fake.postMessage.mock.calls[0][0]).toMatchObject({action:"open",runId:"saved-run"});
  expect(listeners.size).toBe(0);
});
