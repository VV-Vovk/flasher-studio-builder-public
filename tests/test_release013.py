import json,os,struct,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/universal'))
import build,flash_layout as fl,git_libraries as git,native,pio_build as pio

def record(addr,typ,data=b''):
    raw=bytes([len(data)])+addr.to_bytes(2,'big')+bytes([typ])+data
    return ':'+(raw+bytes([-sum(raw)%256])).hex().upper()+'\n'

class FlashTests(unittest.TestCase):
    def test_extended_hex(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'f.hex';p.write_text(record(0,4,b'\x08\x00')+record(0,0,b'ab')+record(2,0,b'cd')+record(0,1))
            self.assertEqual(fl.ihex(p),[{'start':0x08000000,'endExclusive':0x08000004,'size':4}])
    def test_bad_hex(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'f.hex';p.write_text(':0100000000FE\n:00000001FF\n')
            with self.assertRaises(ValueError):fl.ihex(p)
    def test_hex_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'f.hex';p.write_text(record(1,0,b'ab')+record(2,0,b'cd')+record(0,1))
            with self.assertRaisesRegex(ValueError,'Overlapping'):fl.ihex(p)
    def test_uf2(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'f.uf2';b=bytearray(512);struct.pack_into('<8I',b,0,0x0A324655,0x9E5D5157,0x2000,0x10000000,256,0,1,0xe48bff56);struct.pack_into('<I',b,508,0x0AB16F30);p.write_bytes(b)
            r,f=fl.uf2(p);self.assertEqual(r[0]['start'],0x10000000);self.assertEqual(f,0xe48bff56)
            p.write_bytes(b+b)
            with self.assertRaises(ValueError):fl.uf2(p)
    def test_idf(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'bootloader').mkdir();(p/'bootloader/boot.bin').write_bytes(b'abc');(p/'app.bin').write_bytes(b'abcd');(p/'flasher_args.json').write_text(json.dumps({'flash_files':{'0x0':'bootloader/boot.bin','0x10000':'app.bin'}}))
            seg,_=fl.idf_segments(p);self.assertEqual([x['offset'] for x in seg],[0,65536])
    def test_idf_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'build';p.mkdir();(p.parent/'secret.bin').touch();(p/'flasher_args.json').write_text(json.dumps({'flash_files':{'0x0':'../secret.bin'}}))
            with self.assertRaises(ValueError):fl.idf_segments(p)
    def test_unknown_bin(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'app.bin').write_bytes(b'hello');out=p/'out';build.package(p,out,{'engine':'test'},'0'*32);m=json.loads((out/'manifest.json').read_text());self.assertFalse(m['automaticFlashingAllowed']);self.assertFalse(m['flashLayout']['entries']);self.assertTrue(m['flashLayout']['warnings'])
    def test_arduino_merge_verification(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);b=p/'build';b.mkdir();c=p/'core';c.mkdir();(c/'boot.bin').write_bytes(b'boot');(b/'app.bin').write_bytes(b'app');(b/'merged.bin').write_bytes(b'boot'+b'\xff'*12+b'app');props=f'recipe.hooks.objcopy.postobjcopy.3.pattern=esptool merge_bin -o "{b}/merged.bin" 0x0 "{c}/boot.bin" 0x10 "{b}/app.bin"'
            seg=fl.arduino_esp(b,props,c);self.assertEqual([x['offset'] for x in seg],[0,16,0]);self.assertTrue(seg[-1]['alternative']);self.assertEqual((b/'boot.bin').read_bytes(),b'boot')
            (b/'app.bin').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError,'does not match'):fl.arduino_esp(b,props,c)
    def test_pio_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);b=p/'build';b.mkdir();pk=p/'packages';pk.mkdir();(pk/'boot.bin').write_bytes(b'boot');(b/'firmware.bin').write_bytes(b'app');meta={'prog_path':str(b/'firmware.elf'),'extra':{'application_offset':'0x10000','flash_images':[{'offset':'0x0','path':str(pk/'boot.bin')}]}}
            self.assertEqual([s['offset'] for s in fl.pio_esp(b,meta,pk)],[0,65536])

class NativeTests(unittest.TestCase):
    def test_examples_detect(self):
        for e in native.ENGINES:
            p=Path(__file__).resolve().parents[1]/'examples/native'/e
            self.assertEqual(build.detect(p),e)
    def test_native_config(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'CMakeLists.txt').write_text('include($ENV{IDF_PATH}/tools/cmake/project.cmake)');(p/'sdkconfig.defaults').write_text('CONFIG_IDF_TARGET="esp32c3"\n');self.assertEqual(native.native_config(p,'esp-idf')[1:],('esp32c3','v5.4.2'))
            with self.assertRaises(ValueError):native.native_config(p,'esp-idf','esp32s3')
    def test_no_ioc_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'project.ioc').touch()
            with self.assertRaises(ValueError):build.detect(p)
    def test_native_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'CMakeLists.txt').write_text('find_package(Zephyr REQUIRED)');(p/'x.ino').touch()
            with self.assertRaisesRegex(ValueError,'Multiple'):build.detect(p)
    def test_no_sdk(self):
        p=Path(__file__).resolve().parents[1]/'examples/native/pico-sdk'
        with patch.dict(os.environ,{'FS_NATIVE_ENGINE':''}):
            with self.assertRaisesRegex(ValueError,'not provisioned'):native.native_build(p,Path('/tmp/not-used'),'pico-sdk','pico','',None)

class GitTests(unittest.TestCase):
    def test_tag_resolution(self):
        url='https://github.com/org/lib.git';commit='a'*40
        def runner(*a,**kw):return subprocess.CompletedProcess(a,0,'b'*40+'\trefs/tags/v1\n'+commit+'\trefs/tags/v1^{}\n','')
        self.assertEqual(git.resolve(url,'v1',runner),commit)
        self.assertEqual(git.resolve(url,commit,runner),commit)
    def test_branch_tag_ambiguity(self):
        def runner(*a,**kw):return subprocess.CompletedProcess(a,0,'b'*40+'\trefs/tags/v1\n'+'a'*40+'\trefs/heads/v1\n','')
        with self.assertRaises(ValueError):git.resolve('https://github.com/org/lib.git','v1',runner)
    def test_invalid_url(self):
        with self.assertRaises(ValueError):git.resolve('file:///etc/passwd','main')
    def test_lock_replay_uses_commit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);records=[]
            def checkout(url,commit,dest,runner):dest.mkdir();(dest/'library.properties').write_text('name=X')
            with patch.object(git,'resolve') as resolve,patch.object(git,'checkout',side_effect=checkout):
                git.install_recipe('https://github.com/org/lib.git','main',p/'X',records,expected='a'*40);resolve.assert_not_called()
            self.assertEqual(records[0]['commit'],'a'*40)

class PioTests(unittest.TestCase):
    def test_unique_search(self):
        text='Found 1 packages (page 1 of 1)\n\nbblanchon/ArduinoJson\nLibrary • 7.3.1 • Published on ...\n'
        self.assertEqual(pio.choose_match(text),'bblanchon/ArduinoJson@7.3.1');self.assertIsNone(pio.choose_match(text.replace('Found 1','Found 2')))
    def test_rewrite_preserves_other_env(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'platformio.ini';pio.rewrite_ini(p,'[env:uno]\nboard=uno\n[env:other]\nboard=nanoatmega328\n','uno',{'lib_deps':['A@1.0','B@2.0']});s=p.read_text();self.assertIn('nanoatmega328',s);self.assertIn('A@1.0',s);self.assertIn('B@2.0',s)
    def test_package_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);q=p/'atmelavr';q.mkdir();(q/'.piopm').write_text(json.dumps({'name':'atmelavr','version':'5.1.0','spec':{'owner':'platformio'}}));self.assertEqual(pio.package_snapshot(p)[0]['version'],'5.1.0')
    def test_hash_detects_content_change(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);f=p/'a.h';f.write_text('1');h=pio.digest_tree(p);f.write_text('2');self.assertNotEqual(h,pio.digest_tree(p))
    def test_auto_and_lock_replay(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{}):
            p=Path(d);original='[env:uno]\nboard=uno\nframework=arduino\nplatform=atmelavr\n';root=p/'input';root.mkdir();ini=root/'platformio.ini';ini.write_text(original)
            def run(*args,**kw):
                if args[:3]==('pio','project','config'):
                    import configparser
                    c=configparser.ConfigParser();c.read(ini);cfg=dict(c['env:uno']);cfg['framework']=['arduino'];cfg['lib_deps']=pio.string_list(cfg.get('lib_deps'))
                    return json.dumps([['env:uno',list(cfg.items())]])
                if args[:3]==('pio','pkg','search'):return 'Found 1 packages\nowner/Example\nLibrary • 1.2.3 • Published\n'
                if args[:3]==('pio','pkg','list'):return 'package report'
                raise AssertionError(args)
            calls=[]
            def compile(*a,**kw):
                calls.append(a)
                if 'owner/Example@1.2.3' not in ini.read_text():return subprocess.CompletedProcess(a,1,'','fatal error: Example.h: No such file or directory')
                q=root/'.pio/libdeps/uno/Example';q.mkdir(parents=True,exist_ok=True);(q/'.piopm').write_text(json.dumps({'name':'Example','version':'1.2.3','spec':{'owner':'owner'}}));(q/'Example.h').write_text('test')
                plat=root/'.pio/platforms/atmelavr';plat.mkdir(parents=True,exist_ok=True);(plat/'.piopm').write_text(json.dumps({'name':'atmelavr','version':'5.1.0','spec':{'owner':'platformio'}}));return subprocess.CompletedProcess(a,0,'ok','')
            with patch.object(pio.subprocess,'run',side_effect=compile):
                _,m=pio.build_pio(root,'uno',run);self.assertEqual(len(calls),2);lock=m['dependencyLock'];self.assertEqual(lock['libDeps'],['owner/Example@1.2.3']);ini.write_text(original);(root/'flasher-lock.json').write_text(json.dumps(lock));_,m2=pio.build_pio(root,'uno',run);self.assertEqual(m2['dependencyLock'],lock)
