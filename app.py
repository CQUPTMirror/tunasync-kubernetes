from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
import uvicorn
import json
import yaml
import os
import re
from configobj import ConfigObj
import logging
from models import JobConfig
from utils import Tunasync, Kubernetes, get_last_n_lines, size_tools, check_num

app = FastAPI()


@app.on_event('startup')
def init():
    global kubernetes, tunasync, default
    config = yaml.safe_load(open('config.yaml', 'r', encoding='utf-8').read())
    default = {
        "storage": config['storageClass'] if 'storageClass' in config else '',
        "node": config['node'] if 'node' in config else '',
        "front": {
            "name": config['front']['name'] if 'name' in config['front'] else '',
            "image": config['front']['image'] if 'image' in config['front'] else '',
            "imagePullSecrets": config['front']['imagePullSecrets'] if 'imagePullSecrets' in config['front'] else (
                config['imagePullSecrets'] if 'imagePullSecrets' in config else '')
        } if 'front' in config else {},
        "imagePullSecrets": config['imagePullSecrets'] if 'imagePullSecrets' in config else ''
    }
    token_path = '/run/secrets/kubernetes.io/serviceaccount/token'
    ca_path = '/run/secrets/kubernetes.io/serviceaccount/ca.crt'
    ns_path = '/run/secrets/kubernetes.io/serviceaccount/namespace'
    kube_config = {
        "host": os.getenv('KUBERNETES_PORT').replace('tcp', 'https'),
        "token": open(token_path).read() if os.path.exists(token_path) else '',
        "ca": ca_path if os.path.exists(ca_path) else '',
        "namespace": open(ns_path).read() if os.path.exists(ns_path) else 'default'
    }
    if 'apiServer' in config:
        if 'url' in config['apiServer']:
            kube_config['host'] = config['apiServer']['url']
        if 'token' in config['apiServer']:
            kube_config['token'] = config['apiServer']['token']
        if 'ca' in config['apiServer']:
            kube_config['ca'] = config['apiServer']['ca']
    if 'namespace' in config:
        kube_config['namespace'] = config['namespace']
    kubernetes = Kubernetes(**kube_config)
    tunasync = Tunasync(f"http://{config['manager']['name']}:{config['manager']['port']}")


def response(content, code: int = 200, format: bool = True):
    if code != 200:
        return JSONResponse(status_code=code, content={"error": content})
    if isinstance(content, str):
        return JSONResponse(status_code=200, content={"msg": content})
    if format:
        return PlainTextResponse(status_code=code, media_type='application/json',
                                 content=json.dumps(content, sort_keys=True, indent=4, allow_nan=False))
    else:
        return JSONResponse(status_code=code, content=content)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(*args):
    return response('query param unexpected', 400)


@app.exception_handler(Exception)
async def exception_handler(*args):
    return response('something error', 500)


async def check_name(name: str) -> bool:
    return False if name not in [i['id'] for i in await tunasync.workers()] else True


async def get_size(name: str) -> str:
    size_df = size_log = ''
    job = await tunasync.jobs(worker=name)
    if not job:
        return ''
    job = job[0]
    if 'status' in job:
        if job['status'] == 'success':
            lines = await get_last_n_lines(name, 20)
            for line in lines:
                if 'size' in line.lower():
                    size_line = re.findall(r'(\d+\.?\d+?[BKMGTP])', line)
                    if size_line and size_tools.XiB_MB(size_log) < size_tools.XiB_MB(size_line[0]):
                        size_log = size_line[0]
        elif job['status'] == 'syncing':
            try:
                provider = ConfigObj((await kubernetes.config(name)).split('\n'), list_values=False)['server'][
                    'mirrors']['provider'].replace('"', '')
            except:
                provider = ''
            if 'rsync' in provider:
                lines = await get_last_n_lines(name, 5)
                for line in lines:
                    if 'B/s' in line:
                        parts = line.split()
                        if len(parts) >= 4:
                            size_log = size_tools.XB_XiB(parts[0])
    pod = await kubernetes.pod(name=name, ready=True)
    if pod:
        size_df = size_tools.format(int(
            (await kubernetes.exec(pod[0]['name'], ['df', f'/data/mirrors/{name}', '--output=used'])).split('\n')[1]))
    if size_log:
        logging.debug(f'Size in log is {size_log}')
    if size_df:
        logging.debug(f'Size get by df is {size_df}')
    if size_tools.XiB_MB(size_df) < size_tools.XiB_MB(size_log):
        size = size_log
    else:
        size = size_df
    if size == '' or str(size).startswith('0'):
        size = job['size']
        if size == 'unknown':
            size = ''
    return size


@app.get('/init')
async def setup():
    if not await kubernetes.get('deploy', 'tunasync-manager'):
        logging.warning('未发现 manager, 开始部署...')
        config = yaml.safe_load(open('config.yaml', 'r', encoding='utf-8').read())
        if await kubernetes.apply('pvc', 'data', storageclass=default['storage'], data_size='5Gi'):
            logging.debug('创建 PVC 成功')
        else:
            logging.warning('创建 PVC 失败')
            return response('create PVC failed', 500)
        if await kubernetes.apply('svc', config['manager']['name'], port=config['manager']['port']):
            logging.debug('创建 SVC 成功')
        else:
            logging.warning('创建 SVC 失败')
            return response('create SVC failed', 500)
        volumeMounts = [{'mountPath': '/var/lib/tunasync', 'name': 'data'}]
        volumes = [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'data'}}]
        if await kubernetes.apply('deploy', config['manager']['name'], image=config['manager']['image'],
                                  port=config['manager']['port'], node=default['node'], volumeMounts=volumeMounts,
                                  volumes=volumes):
            logging.debug('创建 Deployment 成功')
        else:
            logging.warning('创建 Deployment 失败')
            return response('create Deployment failed', 500)
        logging.warning('部署成功')
    return response('OK')


@app.get('/node')
async def node_list():
    node = await kubernetes.nodes()
    if not node:
        return response('failed to list nodes', 500)
    return response({'msg': 'success', 'data': node})


@app.get('/manager')
@app.get('/front')
async def manage_info(request: Request = None):
    path = request.url.path.split('/')[-1]
    if path == 'manager':
        name = 'tunasync-manager'
    elif path == 'front' and default['front'] and default['front']['name']:
        name = default['front']['name']
    else:
        return response('illegal request', 400)
    data = []
    pods = await kubernetes.pod(name=name, ready=True)
    for pod in pods:
        top = await kubernetes.top(pod['name'])
        if top and 'usage' in top:
            pod['usage'] = top['usage']
        data.append(pod)
    if data:
        return response({'msg': 'success', 'data': data})
    else:
        return response('no ready pod or something wrong', 404)


@app.post('/front')
async def front_deploy(addition: str = None):
    if not default['front']:
        return response('front not config', 400)
    volumeMounts = [
        {'mountPath': '/etc/caddy/Caddyfile', 'name': 'caddy-conf', 'subPath': 'Caddyfile', 'readOnly': True},
        {'mountPath': '/usr/share/caddy/static', 'name': 'static', 'readOnly': True},
        {'mountPath': '/usr/share/caddy/status.html', 'name': 'status-html', 'subPath': 'status.html', 'readOnly': True}
    ]
    workers = await tunasync.workers()
    if addition:
        workers.append({"id": addition})
    for i in workers:
        if i["id"] == "pypi":
            volumeMounts.append(
                {'mountPath': '/usr/share/caddy/pypi', 'name': 'pypi', 'subPath': 'web', 'readOnly': True})
        else:
            volumeMounts.append({'mountPath': f'/usr/share/caddy/{i["id"]}', 'name': i["id"], 'readOnly': True})
    volumes = [{'name': i["id"], 'persistentVolumeClaim': {'claimName': f'{i["id"]}-data'}} for i in workers]
    volumes.append({'name': 'caddy-conf', 'configMap': {'name': 'caddy-conf'}})
    volumes.append({'name': 'static', 'configMap': {'name': 'mirrors-static'}})
    volumes.append({'name': 'status-html', 'configMap': {'name': 'status-html'}})
    if await kubernetes.apply('daemon_set', default['front']['name'], node=default['node'],
                              image=default['front']['image'], port=6000, volumeMounts=volumeMounts, volumes=volumes,
                              imagePullSecrets=default['front']['imagePullSecrets']):
        logging.debug('更新前端成功')
        return response('reload front succeed')
    else:
        logging.warning('前端更新失败')
        return response('reload front failed', 500)


@app.delete('/manager')
@app.delete('/front')
@app.delete('/job/{name}/pod')
async def pod_restart(name: str = '', request: Request = None):
    path = request.url.path.split('/')[-1]
    if path == 'manager':
        name = 'tunasync-manager'
    elif path == 'front':
        if default['front'] and default['front']['name']:
            name = default['front']['name']
        else:
            return response('front not config', 500)
    elif not await check_name(name):
        return response('job not exists', 404)
    if await kubernetes.restart(name):
        return response(f'restart {name} succeed')
    else:
        return response('restart failed', 500)


@app.post('/job')
async def job_creator(req: JobConfig):
    if not req.name or not req.upstream:
        return response('not include name or upstream', 400)
    name = req.name
    if await check_name(name):
        return response('job already exists', 400)
    if req.image:
        image = req.image
    else:
        image = 'ztelliot/tunasync_worker:rsync'
    if req.data_size:
        data_size = req.data_size
    else:
        data_size = '1Ti'
    if req.node:
        node = req.node
    else:
        node = default['node']
    if node and node not in await kubernetes.nodes():
        return response('selected node not exists', 400)
    data = req.dict()
    if not data['provider']:
        data['provider'] = 'rsync'
    if data['provider'] not in ['rsync', 'command', 'two-stage-rsync']:
        return response('unsupported provider', 400)
    if not data['concurrent'] or check_num(data['concurrent']):
        data['concurrent'] = 3
    if not data['interval'] or check_num(data['interval']):
        data['interval'] = 1440
    if data['provider'] == 'command' and ('command' not in data or not data['command']):
        return response('command provider should specify the command', 400)
    if await kubernetes.apply('cm', name, manager=tunasync.api, data=data):
        logging.debug(f'生成 {name} 配置文件成功')
    else:
        logging.warning(f'生成 {name} 配置文件失败')
        return response('something error when apply config map', 500)
    if await kubernetes.apply('pvc', f"{name}-data", storageclass=default['storage'], data_size=data_size):
        logging.debug(f'生成 {name} 储存卷成功')
    else:
        logging.warning(f'生成 {name} 储存卷失败')
        return response('something error when apply persistent volume claim', 500)
    if await kubernetes.apply('svc', name, port=6000):
        logging.debug(f'生成 {name} 服务成功')
    else:
        logging.warning(f'生成 {name} 服务失败')
        return response('something error when apply service', 500)
    volumeMounts = [
        {'mountPath': '/var/log/tunasync', 'name': 'data'},
        {'mountPath': f"/data/mirrors/{name}", 'name': f"{name}-data"},
        {'mountPath': '/etc/tunasync/', 'name': name}
    ]
    volumes = [
        {'name': 'data', 'persistentVolumeClaim': {'claimName': 'data'}},
        {'name': f"{name}-data", 'persistentVolumeClaim': {'claimName': f"{name}-data"}},
        {'name': name, 'configMap': {'name': name}}
    ]
    if await kubernetes.apply('deploy', name, node=node, image=image, port=6000, volumeMounts=volumeMounts,
                              volumes=volumes, imagePullSecrets=default['imagePullSecrets']):
        logging.debug(f'部署 {name} 成功')
        front_res = await front_deploy(name)
        if front_res.status_code != 200:
            logging.warning('更新前端服务失败')
            return response(f'create {name} succeed, but reload front failed')
        logging.debug('更新前端服务成功')
        return response(f'create {name} succeed')
    else:
        logging.warning(f'部署 {name} 失败')
        return response('something error when apply deployment', 500)


@app.get('/job')
async def job_list(status: str = 'all', filter: str = ''):
    if status == 'all' or status == 'disabled':
        jobs = {i['id']: {'name': i['id'], 'status': 'disabled'} for i in await tunasync.workers()}
    else:
        jobs = {}
    for i in await tunasync.jobs():
        if (status != 'all' and status != i['status']) or filter not in i['name']:
            if i['name'] in jobs:
                del jobs[i['name']]
        else:
            jobs[i['name']] = i
    data = json.loads(json.dumps(jobs, sort_keys=True))
    for i in data:
        data[i]['pods'] = []
        pods = await kubernetes.pod(name=i)
        for pod in pods:
            top = await kubernetes.top(pod['name'])
            if top and 'usage' in top:
                pod['usage'] = top['usage']
            data[i]['pods'].append(pod)
    return response({'msg': 'success', 'data': list(data.values())})


@app.get('/job/{name}')
async def job_info(name: str, status: bool = True):
    if not await check_name(name):
        return response('job not exists', 404)
    data = {"status": {}, "spec": {}}
    config = (await kubernetes.config(name)).split('\n')
    if config:
        obj = ConfigObj(config, list_values=False)
        data['spec'] = {
            'concurrent': obj['global']['concurrent'],
            'interval': obj['global']['interval'],
            'provider': obj['server']['mirrors']['provider'].replace('"', ''),
            'upstream': obj['server']['mirrors']['upstream'].replace('"', '')
        }
        if 'command' in obj['server']['mirrors']:
            data['spec']['command'] = obj['server']['mirrors']['command'].replace('"', '')
        if 'rsync_options' in obj['server']['mirrors']:
            rsync_options = obj['server']['mirrors']['rsync_options'][1:-1].replace('"', '').replace(' ', '').split(',')
            if '--info=progress2' in rsync_options:
                rsync_options.remove('--info=progress2')
            if rsync_options:
                data['spec']['rsync_options'] = rsync_options
        if 'memory_limit' in obj['server']['mirrors']:
            data['spec']['memory_limit'] = obj['server']['mirrors']['memory_limit'].replace('"', '')
        if 'size_pattern' in obj['server']['mirrors']:
            data['spec']['size_pattern'] = obj['server']['mirrors']['size_pattern'].replace('"', '')
        if 'mirrors.env' in obj:
            data['spec']['addition_option'] = {i: obj['mirrors.env'][i].replace('"', '') for i in obj['mirrors.env']}
        data['spec']['data_size'] = await kubernetes.pvc_size(f'{name}-data')
        node, image = await kubernetes.deploy_node_image(name)
        if node:
            data['spec']['node'] = node
        data['spec']['image'] = image
        del obj
    if status:
        job = await tunasync.jobs(worker=name)
        if job:
            data['status'] = job[0]
        else:
            data['status'] = {'name': name, 'status': 'disabled'}
        data['status']['pods'] = []
        pods = await kubernetes.pod(name=name)
        for pod in pods:
            top = await kubernetes.top(pod['name'])
            if top and 'usage' in top:
                pod['usage'] = top['usage']
            data['status']['pods'].append(pod)
        data['status']['data_size'] = await kubernetes.pvc_size(f'{name}-data')
        if 'status' in job and job['status'] == 'syncing' and 'rsync' in data['spec']['provider']:
            rstatus = {'rsync_size': '', 'file_name': '', 'remain': '', 'speed': '', 'rate': ''}
            lines = await get_last_n_lines(name, 5)
            for line in lines:
                if 'B/s' in line:
                    if 'xfr' in line:
                        chk = str(re.findall(r'[(](.*?)[)]', line)[0])
                        rstatus['chk_now'] = re.findall(r'[#](.*?)[,]', chk)[0]
                        rstatus['chk_remain'] = re.findall(r'[=](.*?)[/]', chk)[0]
                        rstatus['total'] = chk.split("/")[1]
                    parts = line.split()
                    if len(parts) >= 4:
                        rstatus['rsync_size'] = size_tools.XB_XiB(parts[0])
                        rstatus['rate'] = parts[1]
                        rstatus['speed'] = parts[2]
                        rstatus['remain'] = parts[3]
                elif line and line != '\n':
                    files = line.split('/')
                    rstatus['file_name'] = files[-1].replace('\n', '')
            try:
                rstatus['chk_now'] = int(rstatus['chk_now'])
                rstatus['chk_remain'] = int(rstatus['chk_remain'])
                rstatus['total'] = int(rstatus['total'])
            except:
                rstatus['chk_now'] = rstatus['chk_remain'] = rstatus['total'] = 0
            data['status'].update(rstatus)
    return response({'msg': 'success', 'data': data})


@app.get('/job/{name}/log')
async def job_log(name: str, line: int = 0):
    if not await check_name(name):
        return PlainTextResponse(status_code=404, content='Job Not Found')
    if line:
        if isinstance(line, int):
            content = ''
            for l in await get_last_n_lines(name, line):
                content += l + '\n'
            return PlainTextResponse(content=content)
        else:
            return PlainTextResponse(status_code=400, content='line not int')
    else:
        return FileResponse(f'/var/lib/tunasync/{name}/latest')


@app.patch('/job/{name}')
async def job_modify(name: str, req: JobConfig):
    data = req.dict()
    conf = await job_info(name, status=False)
    if conf.status_code != 200:
        return response('job not exists', 404)
    ori = json.loads(conf.body)['data']['spec']
    for i in ori:
        if i not in data or not data[i]:
            data[i] = ori[i]
    diff = False
    for i in data:
        if i in ['data_size', 'image', 'node'] or (i in ori and data[i] == ori[i]) or (i not in ori and not data[i]):
            pass
        else:
            diff = True
            break
    if diff:
        if 'provider' in data:
            if data['provider'] not in ['rsync', 'command', 'two-stage-rsync']:
                return response('unsupported provider', 400)
            if data['provider'] == 'command' and ('command' not in data or not data['command']):
                return response('command provider should specify the command', 400)
        if check_num(data['concurrent']):
            data['concurrent'] = 3
        if check_num(data['interval']):
            data['interval'] = 1440
        if await kubernetes.apply('cm', name, manager=tunasync.api, data=data):
            if await tunasync.cmd(name, 'reload') and await tunasync.cmd(name, 'restart') and \
                    await tunasync.cmd(name, 'start'):
                logging.debug(f'修改 {name} 配置文件成功')
            else:
                logging.warning(f'修改 {name} 配置文件失败')
                return response('failed to reload or start job', 500)
        else:
            logging.warning(f'修改 {name} 配置文件失败')
            return response('something error when apply config map', 500)
    if data['data_size'] != ori['data_size']:
        if await kubernetes.apply('pvc', f"{name}-data", storageclass=default['storage'], data_size=data['data_size']):
            logging.debug(f'修改 {name} 储存卷成功')
        else:
            logging.warning(f'修改 {name} 储存卷失败')
            return response('something error when apply persistent volume claim', 500)
    if data['image'] != ori['image'] or (data['node'] and 'node' not in ori) or (
            data['node'] and 'node' in ori and data['node'] != ori['node']):
        if data['node'] and data['node'] in await kubernetes.nodes():
            node = data['node']
        else:
            node = ''
        if await kubernetes.apply('deploy', name, node=node, image=data['image'], port=6000, volumeMounts=[
            {'mountPath': '/var/log/tunasync', 'name': 'data'},
            {'mountPath': f"/data/mirrors/{name}", 'name': f"{name}-data"},
            {'mountPath': '/etc/tunasync/', 'name': name}
        ], volumes=[
            {'name': 'data', 'persistentVolumeClaim': {'claimName': 'data'}},
            {'name': f"{name}-data", 'persistentVolumeClaim': {'claimName': f"{name}-data"}},
            {'name': name, 'configMap': {'name': name}}
        ]):
            logging.debug(f'部署 {name} 成功')
        else:
            logging.warning(f'部署 {name} 失败')
            return response('something error when apply deployment', 500)
    return response('success')


@app.post('/job/{name}/{cmd}')
async def job_manage(name: str, cmd: str):
    if not await check_name(name):
        return response('job not exists', 404)
    if cmd in ['start', 'stop', 'restart']:
        if not await tunasync.cmd(name, cmd):
            return response('failed', 500)
    elif cmd in ['enable', 'disable']:
        if not await tunasync.cmd(name, cmd) or not await tunasync.flush_disabled():
            return response('failed', 500)
    elif cmd == 'reload':
        if not await tunasync.cmd(name, 'reload'):
            return response('failed', 500)
    elif cmd == 'refresh':
        if not await tunasync.set_size(name, name, await get_size(name)):
            return response('failed', 500)
    else:
        return response('command not exists', 404)
    return response('success')


@app.delete('/job/{name}')
async def job_delete(name: str):
    if not await check_name(name):
        return response('job not exists', 404)
    failed = []
    if not await tunasync.cmd(name, 'disable'):
        failed.append('disable')
    if not await kubernetes.delete('deploy', name, force=True):
        failed.append('deployment')
    if not await kubernetes.delete('svc', name, force=True):
        failed.append('service')
    if not await kubernetes.delete('cm', name, force=True):
        failed.append('config map')
    if not await tunasync.delete_worker(name):
        failed.append('worker')
    if not await tunasync.flush_disabled():
        failed.append('flush')
    if not failed:
        return response('success')
    else:
        return response(f'some error happened in {failed}', 500)


@app.post('/job/refresh')
async def job_refresh(update: bool = False, retry: bool = False):
    failed = False
    jobs = await tunasync.jobs()
    for job in jobs:
        name = job['name']
        if update:
            size = await get_size(name)
            if await tunasync.set_size(name, name, size):
                logging.debug(f'{name} 当前大小为 {size}，更新数据库成功')
            else:
                failed = True
                logging.warning(f'{name} 当前大小为 {size}，更新数据库失败')
        if retry and job['status'] == 'failed':
            if await tunasync.cmd(name, 'start'):
                logging.debug(f'{name} 同步失败，重新开始')
            else:
                failed = True
                logging.warning(f'{name} 同步失败，重开失败')
    if failed:
        return response('something failed', 500)
    return response('success')


if __name__ == '__main__':
    uvicorn.run(app=app, host="0.0.0.0", port=8080)
