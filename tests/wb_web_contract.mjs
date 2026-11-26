// Cross-check real GNU outputs against the independently implemented Web audit.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const [out,web]=process.argv.slice(2);
const {auditWbElf,wbCheckMemoryFit}=await import(pathToFileURL(resolve(web,'wb-memory.js')).href);
const {parseHex}=await import(pathToFileURL(resolve(web,'programmers.js')).href);
const m=JSON.parse(readFileSync(resolve(out,'manifest.json'),'utf8')).build;
const hex=parseHex(readFileSync(resolve(out,'firmware.hex'),'utf8'));
const audit=auditWbElf(new Uint8Array(readFileSync(resolve(out,'firmware.elf'))),m.memory.flashKiB,hex,m.wbOtaOrigin??0x08000000,m.memory.ramKiB);
assert.deepEqual(audit,m.wbMemoryAudit);
if(m.wbOtaLayout){
 const {checkWbOtaImage}=await import(pathToFileURL(resolve(web,'wb-ota.js')).href);
 const {checkWbBuildMetadata,checkWbFullProjectHex}=await import(pathToFileURL(resolve(web,'universal.js')).href);
 const image=checkWbOtaImage(m.target,hex,m.memory.flashKiB).image;
 assert.deepEqual(image,new Uint8Array(readFileSync(resolve(out,'firmware.bin'))));
 checkWbBuildMetadata(m,{engine:'stm32cubeide-gcc',nativeTarget:m.target,ext:'zip'});
 checkWbFullProjectHex(m,new Map(['firmware.hex','firmware.elf','firmware.bin'].map(f=>[f,new Uint8Array(readFileSync(resolve(out,f)))])));
 console.log('WB_REAL_OTA_WEB_CONTRACT_PASS');
}else{
const p={audit,flashKiB:m.memory.flashKiB};
const rv=(0x80000000|(10<<18)|((m.memory.ramKiB===12?3:15)<<25))>>>0;
assert.doesNotThrow(()=>wbCheckMemoryFit(p,65536,rv,0,m.memory.ramKiB));
assert.throws(()=>wbCheckMemoryFit(p,65536,0x80000000,0,m.memory.ramKiB),/boundary/);
console.log('WB_REAL_WEB_CONTRACT_PASS');
}
