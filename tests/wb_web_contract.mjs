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
const audit=auditWbElf(new Uint8Array(readFileSync(resolve(out,'firmware.elf'))),m.memory.flashKiB,hex);
assert.deepEqual(audit,m.wbMemoryAudit);
const p={audit,flashKiB:m.memory.flashKiB};
const rv=(0x80000000|(10<<18)|(15<<25))>>>0;
assert.doesNotThrow(()=>wbCheckMemoryFit(p,65536,rv,0));
assert.throws(()=>wbCheckMemoryFit(p,65536,0x80000000,0),/boundary/);
console.log('WB_REAL_WEB_CONTRACT_PASS');
