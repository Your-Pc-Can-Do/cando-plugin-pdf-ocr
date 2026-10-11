"""OCR task state. This is plugin code, not a CanDo task protocol."""
from __future__ import annotations
import copy
import json
import mimetypes
import os
from pathlib import Path
import threading
import time
import uuid

from cando_http import HTTPError, Limits, Server


class PluginError(ValueError):
    pass


class Cancelled(Exception):
    pass


class Context:
    def __init__(self, request, job, cancel, publish, lock):
        self.inputs = [Path(value) for value in request.get('inputs', [])]
        self.options = request.get('options', {})
        self.locale = request.get('locale', 'en')
        self.output_dir = Path(job['outputDir'])
        self.job, self.cancel, self.publish = job, cancel, publish
        self.allocated = []
        self.lock = lock

    def check_cancelled(self):
        if self.cancel.is_set():
            raise Cancelled()

    def progress(self, fraction, message=''):
        self.check_cancelled()
        with self.lock:
            self.job.update(fraction=fraction, message=message)
        self.publish()

    def output_path(self, name):
        self.check_cancelled()
        # Output names come from this tool; never overwrite an input or prior result.
        if not name or Path(name).name != name or any(c in name for c in '\\/:'):
            raise PluginError('Invalid output filename.')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stem, suffix = Path(name).stem, Path(name).suffix
        for index in range(1, 10001):
            target = self.output_dir / (name if index == 1 else f'{stem} ({index}){suffix}')
            try:
                fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                self.allocated.append(target)
                return target
            except FileExistsError:
                continue
        raise PluginError('Too many files with the same name.')

    def add_output(self, path):
        self.check_cancelled()
        path = Path(path).resolve()
        with self.lock:
            self.job['outputs'].append({'path': str(path), 'name': path.name,
                                        'size': path.stat().st_size, 'mime': mimetypes.guess_type(path.name)[0]})

    def result(self, summary='Completed.'):
        return {'summary': summary}

    def cleanup(self):
        complete = {item['path'] for item in self.job['outputs']}
        for path in self.allocated:
            if str(path.resolve()) not in complete:
                path.unlink(missing_ok=True)


def make_server(actions, slug='video-to-gif'):
    jobs, controls, threads = {}, {}, {}
    view = {}
    lock = threading.RLock()
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local'))) / 'app.cando.desktop' / 'outputs' / slug

    def shutdown():
        with lock:
            for control in controls.values():
                control.set()
            workers = list(threads.values())
        deadline = time.monotonic() + 2
        for worker in workers:
            worker.join(max(0, deadline - time.monotonic()))

    server = Server(limits=Limits(json_bytes=1024*1024), on_shutdown=shutdown)
    events = server.events()

    def changed():
        events.publish({'changed': True})

    def snapshot(job):
        return {**{key:copy.deepcopy(value) for key,value in job.items() if key!='outputs'},
                'outputCount':len(job['outputs'])}

    @server.route('GET', '/state')
    def current(_):
        with lock:
            recent=[];size=0
            for job in reversed(list(jobs.values())):
                item=snapshot(job);length=len(json.dumps(item,ensure_ascii=False).encode('utf8'))
                if recent and size+length>512*1024:break
                recent.append(item);size+=length
            return {'jobs': list(reversed(recent)), 'outputRoot': str(base)}

    @server.route('GET', '/view')
    def get_view(_):
        with lock:
            return copy.deepcopy(view)

    @server.route('GET', '/outputs')
    def get_outputs(request):
        try:
            identifier=request.query.get('id',[''])[0]
            offset=int(request.query.get('offset',['0'])[0])
        except (TypeError,ValueError):
            raise HTTPError(400,'Invalid output page.')
        with lock:
            if identifier not in jobs or offset < 0:
                raise HTTPError(404,'Operation not found.')
            outputs=jobs[identifier]['outputs'];rows=[];size=0
            for item in outputs[offset:offset+64]:
                encoded=len(json.dumps(item,ensure_ascii=False).encode('utf8'))
                if rows and size+encoded>512*1024:break
                rows.append(copy.deepcopy(item));size+=encoded
            next_offset=offset+len(rows)
            return {'outputs':rows,'nextOffset':next_offset if next_offset<len(outputs) else None}

    @server.route('POST', '/view')
    def remember(request):
        value = request.json()
        if not isinstance(value, dict):
            raise HTTPError(400, 'View state must be an object.')
        with lock:
            view.clear()
            view.update(value)
        return {'saved': True}

    @server.route('GET', '/events')
    def subscribe(_):
        subscription = events.subscribe()
        changed()  # Re-query state even when completion preceded this subscription.
        return subscription

    def execute(action, value, job, control):
        ctx = Context(value, job, control, changed, lock)
        try:
            result = actions[action](ctx)
            with lock:
                ctx.check_cancelled()
                job.update(status='completed', fraction=1, message=result.get('summary', 'Completed.'))
        except Cancelled:
            with lock:
                job.update(status='cancelled', message='취소됨' if ctx.locale == 'ko' else 'Cancelled.')
        except Exception as error:
            with lock:
                job.update(status='failed', error=str(error)[:2000], message=str(error)[:2000])
        finally:
            try:
                ctx.cleanup()
            except OSError as error:
                with lock:
                    job['cleanupWarning']=str(error)[:2000]
            finally:
                with lock:
                    controls.pop(job['id'], None)
                    threads.pop(job['id'], None)
                changed()

    @server.route('POST', '/start')
    def start(request):
        value = request.json()
        if not isinstance(value, dict) or value.get('action') not in actions:
            raise HTTPError(400, 'Unknown operation.')
        inputs = value.get('inputs', [])
        if not isinstance(inputs, list) or len(inputs) > 512 or not all(isinstance(item, str) for item in inputs) or not isinstance(value.get('options', {}), dict):
            raise HTTPError(400, 'Invalid inputs or options.')
        if any(not Path(item).is_absolute() or not Path(item).is_file() for item in inputs):
            raise HTTPError(400, 'An input file is missing.')
        identifier = uuid.uuid4().hex
        output = value.get('outputDir') or str(base / identifier)
        if not isinstance(output, str) or not Path(output).is_absolute():
            raise HTTPError(400, 'Choose an absolute output folder.')
        job = {'id': identifier, 'actionId': value['action'], 'status': 'running', 'fraction': 0,
               'message': '', 'outputs': [], 'outputDir': output, 'sourcePath':inputs[0] if inputs else None}
        with lock:
            if len(controls) >= 4:
                raise HTTPError(429, 'Four operations are already running.')
            # Keep bounded recent history, never discard a running job.
            for key in list(jobs):
                if len(jobs) < 16:
                    break
                if key not in controls:
                    del jobs[key]
            control = threading.Event()
            worker = threading.Thread(target=execute, args=(value['action'], value, job, control), daemon=True)
            jobs[identifier], controls[identifier], threads[identifier] = job, control, worker
            worker.start()
            return snapshot(job)

    @server.route('POST', '/cancel')
    def cancel(request):
        value = request.json()
        with lock:
            identifier = value.get('id') if isinstance(value, dict) else None
            if identifier not in jobs:
                raise HTTPError(404, 'Operation not found.')
            if identifier in controls:
                controls[identifier].set()
            return snapshot(jobs[identifier])

    return server
