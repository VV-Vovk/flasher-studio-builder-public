import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/universal'))
import native

class CloudRegressions(unittest.TestCase):
    def test_sdk_gitlink_checkout(self):
        # Actual local Git repositories, not mock subprocess calls.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); driver=root/'driver'; parent=root/'parent'; sdk=root/'sdk'
            env={**os.environ,'GIT_ALLOW_PROTOCOL':'file','GIT_AUTHOR_NAME':'Test','GIT_AUTHOR_EMAIL':'test@example.invalid','GIT_COMMITTER_NAME':'Test','GIT_COMMITTER_EMAIL':'test@example.invalid'}
            def git(cwd,*args):return subprocess.run(['git',*args],cwd=cwd,env=env,check=True,capture_output=True,text=True).stdout.strip()
            for repo in (driver,parent):repo.mkdir();git(repo,'init','-b','main')
            (driver/'Inc').mkdir();(driver/'Inc'/'driver.h').write_text('driver');git(driver,'add','.');git(driver,'commit','-m','driver')
            (parent/'Drivers/CMSIS/Include').mkdir(parents=True);(parent/'Drivers/CMSIS/Include/core.h').write_text('core')
            (parent/'Middlewares/Third_Party/FreeRTOS').mkdir(parents=True);(parent/'Middlewares/Third_Party/FreeRTOS/tasks.c').write_text('tasks')
            (parent/'Middlewares/Other').mkdir(parents=True);(parent/'Middlewares/Other/unneeded.c').write_text('unneeded')
            git(parent,'submodule','add',driver.as_uri(),'Drivers/STM32F4xx_HAL_Driver');git(parent,'add','.');git(parent,'commit','-m','parent');git(parent,'tag','v1.0.0')
            subprocess.run(['bash',str(ROOT/'tools/universal/stm32-sdk-checkout.sh'),str(sdk),'f4','v1.0.0',parent.as_uri()],check=True,env=env,capture_output=True,text=True)
            self.assertTrue((sdk/'Drivers/STM32F4xx_HAL_Driver/Inc/driver.h').is_file());self.assertTrue((sdk/'Middlewares/Third_Party/FreeRTOS/tasks.c').is_file());self.assertFalse((sdk/'Middlewares/Other/unneeded.c').exists())
            self.assertEqual(git(sdk/'Drivers/STM32F4xx_HAL_Driver','rev-parse','HEAD'),git(driver,'rev-parse','HEAD'))
    def test_zephyr_success_survives_freeze_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);root=p/'project';root.mkdir();(root/'CMakeLists.txt').write_text('find_package(Zephyr REQUIRED)\nproject(app)')
            sdk=p/'sdk/zephyr';sdk.mkdir(parents=True);(sdk/'.git').mkdir();work=p/'work';work.mkdir()
            def run(*args,**kwargs):
                if args[:2]==('git','rev-parse'):return 'a'*40+'\n'
                if args[:2]==('west','build'):
                    dest=work/'native-build/zephyr';dest.mkdir(parents=True);(dest/'zephyr.hex').write_text(':00000001FF\n');return
                if args[:2]==('west','manifest'):raise subprocess.CalledProcessError(1,args)
                if args[:2]==('west','list'):return f'zephyr\t{sdk}\tv4.1.0\nmissing\t{sdk.parent/"missing"}\tmain\n'
                raise AssertionError(args)
            with patch.dict(os.environ,{'FS_NATIVE_ENGINE':'zephyr','FS_NATIVE_VERSION':'v4.1.0','FS_SDK_PATH':str(sdk)}):
                out,meta=native.native_build(root,work,'zephyr','nrf52840dk/nrf52840','v4.1.0',run)
            self.assertTrue((out/'zephyr.hex').exists());self.assertEqual(meta['westCheckedOutProjects'][0]['commit'],'a'*40);self.assertIn('westManifestWarning',meta);self.assertNotIn('westManifestFrozen',meta)
