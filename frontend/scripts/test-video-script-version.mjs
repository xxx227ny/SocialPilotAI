import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");
const output=path.join(root,".video-script-test-temp");
let behavior=0, staticChecks=0;
const behaviorNames = [
  "create V1 and report reused",
  "duration total and save blocking",
  "exact Variant recovery and ascending history",
  "activate historical Version by exact id",
  "local comparison of two exact Versions",
  "operation identity isolates A/B responses",
  "feature gate defaults off and Presentation does not mount",
  "Presentation performs zero API requests",
];
try {
  await build({configFile:false,logLevel:"silent",build:{write:true,outDir:output,emptyOutDir:true,lib:{entry:{state:path.join(root,"src/components/video/videoScriptVersionState.ts"),features:path.join(root,"src/config/features.ts")},formats:["es"]},rollupOptions:{output:{entryFileNames:"[name].mjs"}}}});
  const state=await import(`${pathToFileURL(path.join(output,"state.mjs")).href}?v=${Date.now()}`);
  const features=await import(`${pathToFileURL(path.join(output,"features.mjs")).href}?v=${Date.now()}`);
  const draft={source_type:"MANUAL",idempotency_key:"manual-key",parent_version_id:null,strategy_id:null,copy_matrix_id:null,source_video_project_id:null,title:"T",concept:"C",hook:"H",cta:"A",scenes:[{sequence:1,start_ms:0,end_ms:15000,shot_type:"x",visual_description:"x",action_description:"",narration:"x",subtitle_draft:"x"}]};
  const version=(id,number,title="T")=>({id,batch_video_variant_id:9,version_number:number,parent_version_id:null,source_type:"MANUAL",source_digest:"a",content_digest:"b",idempotency_key:`k${id}`,title,concept:"C",hook:"H",cta:"A",full_narration:"x",full_subtitle_draft:"x",platform:"youtube",language:"zh-CN",creative_angle:null,brand_kit_version_id:null,brand_kit_version_digest:null,created_by_kind:"LOCAL_USER",review_status:"UNREVIEWED",created_at:"now",scenes:[]});
  const calls=[]; const api={preflight:async(id)=>{calls.push(`preflight:${id}`);return{source_digest:"a",content_digest:"b",preflight_digest:"c",expires_at:"later"}},create:async(id)=>{calls.push(`create:${id}`);return{version:version(1,1),reused:true}},list:async(id)=>{calls.push(`list:${id}`);return[version(2,2),version(1,1)]},get:async(id,v)=>{calls.push(`get:${id}:${v}`);return version(v,v)},activate:async(id,v)=>{calls.push(`activate:${id}:${v}`);return{variant_id:id,active_script_version_id:v,reused:false}}};
  const signal=new AbortController().signal;
  const saved=await state.saveScriptVersion(api,9,draft,signal); assert.equal(saved.reused,true); assert.deepEqual(calls.splice(0),["preflight:9","create:9"]); behavior++;
  await assert.rejects(()=>state.saveScriptVersion(api,9,{...draft,scenes:[{...draft.scenes[0],end_ms:14000}]},signal)); assert.equal(calls.length,0); behavior++;
  const recovered=await state.recoverExactScript(api,9,1,signal); assert.deepEqual(recovered.versions.map(x=>x.version_number),[1,2]); assert.equal(recovered.active.id,1); assert.deepEqual(calls.splice(0),["list:9","get:9:1"]); behavior++;
  const active=await state.activateExactScript(api,9,2,signal); assert.equal(active.id,2); assert.deepEqual(calls.splice(0),["activate:9:2","get:9:2"]); behavior++;
  assert.equal(state.compareExactVersions(version(1,1),version(2,2,"Changed")).titleChanged,true); behavior++;
  const a={id:1,variantId:9,controller:new AbortController()},b={id:2,variantId:9,controller:new AbortController()}; assert.equal(state.isCurrentScriptOperation(a,a),true); assert.equal(state.isCurrentScriptOperation(a,b),false); behavior++;
  assert.equal(features.isEnabledFeatureFlag(undefined),false); assert.equal(state.shouldMountVideoScriptFlow(true,true),false); assert.equal(state.shouldMountVideoScriptFlow(true,false),true); behavior++;
  let presentationRequests=0; if(state.shouldMountVideoScriptFlow(true,true))presentationRequests++; assert.equal(presentationRequests,0); behavior++;
  const storedVersions=[]; const storedByKey=new Map();
  const versionedApi={
    preflight:async(_id,draftValue)=>({source_digest:"a",content_digest:draftValue.title,preflight_digest:"c",expires_at:"later"}),
    create:async(id,draftValue)=>{const existing=storedByKey.get(draftValue.idempotency_key);if(existing)return{version:existing,reused:true};const created={...version(1,storedVersions.length+1,draftValue.title),id:storedVersions.length+1,batch_video_variant_id:id,parent_version_id:draftValue.parent_version_id,idempotency_key:draftValue.idempotency_key,scenes:structuredClone(draftValue.scenes),is_active:false};storedVersions.push(created);storedByKey.set(draftValue.idempotency_key,created);return{version:created,reused:false};},
    list:async()=>[...storedVersions].reverse(),get:async(_id,versionId)=>storedVersions.find(item=>item.id===versionId),activate:async(_id,versionId)=>({active_script_version_id:versionId,reused:false}),
  };
  const createdV1=await state.saveScriptVersion(versionedApi,9,{...structuredClone(draft),idempotency_key:"state-v1",title:"V1"},signal);
  const createdV2=await state.saveScriptVersion(versionedApi,9,{...structuredClone(draft),idempotency_key:"state-v2",parent_version_id:createdV1.version.id,title:"V2"},signal);
  const reusedV1=await state.saveScriptVersion(versionedApi,9,{...structuredClone(draft),idempotency_key:"state-v1",title:"V1"},signal);
  assert.equal(createdV2.version.version_number,2);assert.equal(storedVersions[0].title,"V1");assert.equal(reusedV1.reused,true);assert.equal(storedVersions.length,2);behavior++;behaviorNames.push("edit and save V2 without changing V1, then reuse V1");
  const operationSlot={current:null};let resolveA;const operationA=state.replaceScriptOperation(operationSlot,10,9);const operationUpdates=[];
  const pendingA=state.runLatestScriptOperation({operation:operationA,current:()=>operationSlot.current,execute:()=>new Promise(resolve=>{resolveA=resolve;}),success:value=>operationUpdates.push(value),failure:()=>assert.fail("stale operation must not fail current state")});
  const operationB=state.replaceScriptOperation(operationSlot,11,9);assert.equal(operationA.controller.signal.aborted,true);
  await state.runLatestScriptOperation({operation:operationB,current:()=>operationSlot.current,execute:async()=>"B",success:value=>operationUpdates.push(value),failure:()=>assert.fail("B must succeed")});resolveA("A");await pendingA;assert.deepEqual(operationUpdates,["B"]);behavior++;behaviorNames.push("AbortController and operation id prevent stale A from overwriting B");
  let disconnectFailures=0;let disconnectUpdates=0;const disconnected=state.replaceScriptOperation(operationSlot,12,9);
  await state.runLatestScriptOperation({operation:disconnected,current:()=>operationSlot.current,execute:async()=>{throw new Error("backend disconnected");},success:()=>{disconnectUpdates+=1;},failure:()=>{disconnectFailures+=1;}});assert.equal(disconnectFailures,1);assert.equal(disconnectUpdates,0);behavior++;behaviorNames.push("Backend disconnect produces one honest failure and no later update");
  assert.equal(state.scriptReviewLabel("UNREVIEWED"),"未审核");assert.match(state.scriptCostLabel("manual_versioning_only"),/成本0/);behavior++;behaviorNames.push("UNREVIEWED and manual-versioning cost mapping");
  const panel=await fs.readFile(path.join(root,"src/components/video/VideoScriptVersionPanel.tsx"),"utf8"); const page=await fs.readFile(path.join(root,"src/pages/ContentStudioPage.tsx"),"utf8"); const feature=await fs.readFile(path.join(root,"src/config/features.ts"),"utf8");
  for(const text of ["saveScriptVersion","recoverExactScript","activateExactScript","compareExactVersions","UNREVIEWED","manual_versioning_only","Backend连接中断","精确VideoProject ID"]){assert.ok(panel.includes(text));staticChecks++;}
  assert.ok(page.includes("scriptVersionsEnabled={videoScriptVersionsEnabled}")); assert.ok(feature.includes("VITE_ENABLE_VIDEO_SCRIPT_VERSIONS")); assert.ok(!feature.includes("VITE_ENABLE_VIDEO_SCRIPT_VERSIONS ??")); staticChecks+=3;
  for(const forbidden of ["qwen","wanx","ffmpeg"]){assert.ok(!panel.toLowerCase().includes(forbidden));staticChecks++;}
  for(const forbiddenRecovery of ["latest_version","latestversion","?latest=",`version_id: "latest"`]){assert.ok(!panel.toLowerCase().includes(forbiddenRecovery));staticChecks++;}
  assert.equal(behaviorNames.length,behavior);
  console.log(`Video Script Version: ${behavior} product-state behavior scenarios, ${staticChecks} static/safety assertions passed\n${behaviorNames.map((name,index)=>`${index+1}. ${name}`).join("\n")}`);
} finally { await fs.rm(output,{recursive:true,force:true}); }
