"""Plugin-owned inference process: the HTTP backend stays alive when a task is cancelled."""
import multiprocessing
import sys
from task_runtime import PluginError

def _engine_process(pipe, pages):
    sys.stdout=sys.stderr
    try:
        import ocr_engine
        engine=ocr_engine.load_engine(pages)
        pipe.send({'ready':True,'name':engine.name})
        while True:
            command=pipe.recv()
            if command['op']=='stop':break
            image=command['image']
            try:pipe.send({'result':engine.recognize(image)})
            finally:image.close()
    except EOFError:
        pass
    except BaseException as exc:
        try:pipe.send({'error':str(exc)[:2000]})
        except (OSError,EOFError):pass
    finally:pipe.close()

class OCRSession:
    def __init__(self,ctx,pages):
        self.ctx=ctx
        mp=multiprocessing.get_context('spawn')
        self.pipe,child=mp.Pipe()
        self.process=mp.Process(target=_engine_process,args=(child,pages),daemon=True)
        self.process.start();child.close()
        try:self.name=self._receive()['name']
        except BaseException:self.close();raise
    def _receive(self):
        while True:
            self.ctx.check_cancelled()
            if self.pipe.poll(.05):
                try:response=self.pipe.recv()
                except EOFError:raise PluginError('OCR process stopped unexpectedly.') from None
                if 'error' in response:raise PluginError(response['error'])
                return response
            if not self.process.is_alive():raise PluginError('OCR process stopped unexpectedly.')
    def recognize(self,image):
        self.ctx.check_cancelled()
        self.pipe.send({'op':'recognize','image':image})
        return self._receive()['result']
    def close(self):
        if self.process.is_alive():
            try:self.pipe.send({'op':'stop'})
            except (BrokenPipeError,EOFError,OSError):pass
            self.process.join(.15)
            if self.process.is_alive():self.process.terminate();self.process.join(1)
            if self.process.is_alive():self.process.kill();self.process.join()
        self.pipe.close()
