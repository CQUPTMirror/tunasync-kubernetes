from kubernetes_asyncio import client
from kubernetes_asyncio.stream import WsApiClient
from kubernetes_asyncio.client.rest import ApiException
import aiohttp
import asyncio
from configobj import ConfigObj
import logging


class size_tools(object):
    @staticmethod
    def format(size_k: int) -> str:
        size_m = size_k / 1024
        size_g = size_m / 1024
        size_t = size_g / 1024
        if size_t > 1:
            human_readable_size = str(round(size_t, 2)) + 'T'
        elif size_g > 1:
            human_readable_size = str(round(size_g, 2)) + 'G'
        elif size_m > 1:
            human_readable_size = str(round(size_m, 2)) + 'M'
        else:
            human_readable_size = str(round(size_k, 2)) + 'K'
        return human_readable_size

    @staticmethod
    def XB_XiB(size_b: str) -> str:
        if 'T' in size_b.upper():
            size_b = str(round((float(size_b[:-1]) * 0.909), 2)) + 'T'
        elif 'G' in size_b.upper():
            size_b = str(round((float(size_b[:-1]) * 0.931), 2)) + 'G'
        elif 'M' in size_b.upper():
            size_b = str(round((float(size_b[:-1]) * 0.953), 2)) + 'M'
        elif 'K' in size_b.upper():
            size_b = str(round((float(size_b[:-1]) * 0.977), 2)) + 'K'
        else:
            pass
        return size_b

    @staticmethod
    def XiB_MB(size: str) -> int | float:
        if not size:
            return 0
        try:
            if 'T' in size.upper():
                size_b = float(size[:-1]) * 1024 * 1024
            elif 'G' in size.upper():
                size_b = float(size[:-1]) * 1024
            elif 'M' in size.upper():
                size_b = float(size[:-1])
            elif 'K' in size.upper():
                size_b = float(size[:-1]) / 1024
            else:
                size_b = float(size) / (1024 * 1024)
            return size_b
        except:
            return 0


async def get_last_n_lines(name: str, n: int) -> list:
    args = "tail -n {} /var/lib/tunasync/{}/latest".format(n, name)
    proc = await asyncio.create_subprocess_shell(args, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if stdout:
        return stdout.decode().split('\n')
    else:
        return []


def check_num(p) -> bool:
    try:
        return True if p and int(p) > 0 else False
    except:
        return False


class Conf:
    @staticmethod
    def pvc(name: str, args: dict) -> dict:
        data = {
            'kind': 'PersistentVolumeClaim',
            'apiVersion': 'v1',
            'metadata': {
                'name': name,
                'namespace': args['namespace'],
                'annotations': {
                    'volume.beta.kubernetes.io/storage-class': args['storageclass']
                }
            },
            'spec': {
                'accessModes': ['ReadWriteMany'],
                'storageClassName': args['storageclass'],
                'resources': {
                    'requests': {
                        'storage': args['data_size']
                    }
                }
            }
        }
        return data

    @staticmethod
    def svc(name: str, args: dict) -> dict:
        data = {
            'kind': 'Service',
            'apiVersion': 'v1',
            'metadata': {
                'labels': {
                    'app': name
                },
                'name': name,
                'namespace': args['namespace']
            },
            'spec': {
                'ports': [{
                    'port': args['port'],
                    'protocol': 'TCP',
                    'targetPort': args['port']
                }],
                'selector': {
                    'app': name
                }
            }
        }
        return data

    @staticmethod
    def cm(name: str, args: dict) -> dict:
        mirror_conf = ConfigObj(list_values=False)
        mirror_conf['global'] = {'name': f'"{name}"', 'mirror_dir': '"/data/mirrors"',
                                 'log_dir': f'"/var/log/tunasync/{name}"', 'retry': 3,
                                 'concurrent': args['data']['concurrent'], 'interval': args['data']['interval']}
        mirror_conf['manager'] = {'api_base': f'"{args["manager"]}"'}
        mirror_conf['cgroup'] = {'enable': 'false', 'base_path': '""', 'group': '""'}
        mirror = {'name': f'"{name}"', 'provider': f'"{args["data"]["provider"]}"',
                  'upstream': f'"{args["data"]["upstream"]}"', 'use_ipv6': 'false'}
        if args['data']['provider'] == 'command':
            mirror['command'] = f'"{args["data"]["command"]}"'
        elif 'rsync' in args['data']['provider']:
            if isinstance(args['data']['rsync_options'], list):
                op = args['data']['rsync_options']
            else:
                op = args['data']['rsync_options'].split()
            if '--info=progress2' not in op:
                op.append('--info=progress2')
            mirror['rsync_options'] = str(op).replace('\'', '"')
            if args['data']['provider'] == 'two-stage-rsync':
                mirror['stage1_profile'] = '"debian"'
        else:
            pass
        if args['data']['memory_limit']:
            mirror['memory_limit'] = f'"{args["data"]["memory_limit"]}"'
        if args['data']['size_pattern']:
            mirror['size_pattern'] = f'"{args["data"]["size_pattern"]}"'.replace('\\', '\\\\')
        mirror_conf['server'] = {'hostname': f'"{name}"', 'listen_addr': '"0.0.0.0"',
                                 'listen_port': '6000', 'ssl_cert': '""', 'ssl_key': '""', 'mirrors': mirror}
        if args['data']['addition_option']:
            mirror_conf['mirrors.env'] = {}
            for i in args['data']['addition_option']:
                mirror_conf['mirrors.env'][i] = f'"{args["data"]["addition_option"][i]}"'
        data = {
            'kind': 'ConfigMap',
            'apiVersion': 'v1',
            'metadata': {
                'name': name,
                'namespace': args['namespace']
            },
            'data': {
                'worker.conf': '\n'.join(mirror_conf.write())
            }
        }
        return data

    @staticmethod
    def deploy(name: str, args: dict) -> dict:
        data = {
            'kind': 'Deployment',
            'apiVersion': 'apps/v1',
            'metadata': {
                'labels': {
                    'app': name
                },
                'name': name,
                'namespace': args['namespace']
            },
            'spec': {
                'replicas': 1,
                'revisionHistoryLimit': 1,
                'selector': {
                    'matchLabels': {
                        'app': name
                    }
                },
                'template': {
                    'metadata': {
                        'labels': {
                            'app': name
                        }
                    },
                    'spec': {
                        'containers': [{
                            'name': name,
                            'image': args['image'],
                            'imagePullPolicy': 'IfNotPresent',
                            'livenessProbe': {
                                'tcpSocket': {
                                    'port': args['port']
                                },
                                'initialDelaySeconds': 30,
                                'timeoutSeconds': 5,
                                'periodSeconds': 30,
                                'successThreshold': 1,
                                'failureThreshold': 5
                            },
                            'readinessProbe': {
                                'tcpSocket': {
                                    'port': args['port']
                                },
                                'initialDelaySeconds': 30,
                                'timeoutSeconds': 5,
                                'periodSeconds': 10,
                                'successThreshold': 1,
                                'failureThreshold': 5
                            },
                            'volumeMounts': args['volumeMounts'],
                            'ports': [{
                                'name': 'api',
                                'containerPort': args['port'],
                                'protocol': 'TCP'
                            }]
                        }],
                        'volumes': args['volumes']
                    }
                }
            }
        }
        if 'imagePullSecrets' in args and args['imagePullSecrets']:
            data['spec']['template']['spec']['imagePullSecrets'] = [{'name': args['imagePullSecrets']}]
        if 'node' in args and args['node']:
            data['spec']['template']['spec']['nodeSelector'] = {'kubernetes.io/hostname': args['node']}
        return data

    @staticmethod
    def daemon_set(name: str, args: dict) -> dict:
        data = {
            'kind': 'DaemonSet',
            'apiVersion': 'apps/v1',
            'metadata': {
                'labels': {
                    'app': name
                },
                'name': name,
                'namespace': args['namespace']
            },
            'spec': {
                'revisionHistoryLimit': 1,
                'selector': {
                    'matchLabels': {
                        'app': name
                    }
                },
                'template': {
                    'metadata': {
                        'labels': {
                            'app': name
                        }
                    },
                    'spec': {
                        'containers': [{
                            'name': name,
                            'image': args['image'],
                            'imagePullPolicy': 'Always',
                            'livenessProbe': {
                                'tcpSocket': {
                                    'port': 80
                                },
                                'initialDelaySeconds': 30,
                                'timeoutSeconds': 5,
                                'periodSeconds': 30,
                                'successThreshold': 1,
                                'failureThreshold': 5
                            },
                            'readinessProbe': {
                                'tcpSocket': {
                                    'port': 80
                                },
                                'initialDelaySeconds': 30,
                                'timeoutSeconds': 5,
                                'periodSeconds': 10,
                                'successThreshold': 1,
                                'failureThreshold': 5
                            },
                            'volumeMounts': args['volumeMounts'],
                            'ports': [{
                                'name': name,
                                'containerPort': 80,
                                'protocol': 'TCP'
                            }, {
                                'name': 'admin',
                                'containerPort': 9090,
                                'protocol': 'TCP'
                            }]
                        }],
                        'volumes': args['volumes']
                    }
                }
            }
        }
        if 'imagePullSecrets' in args and args['imagePullSecrets']:
            data['spec']['template']['spec']['imagePullSecrets'] = [{'name': args['imagePullSecrets']}]
        if 'node' in args and args['node']:
            data['spec']['template']['spec']['nodeSelector'] = {'kubernetes.io/hostname': args['node']}
        return data


class Kubernetes(object):
    def __init__(self, host: str, token: str, ca: str = None, namespace: str = 'default'):
        configuration = client.Configuration()
        configuration.api_key['BearerToken'] = "Bearer " + token
        configuration.host = host
        if ca:
            configuration.ssl_ca_cert = ca
        else:
            configuration.verify_ssl = False
        self.api_client = client.ApiClient(configuration)
        self.auth_settings = ['BearerToken']
        self.namespace = namespace
        self.api_instance = client.CoreV1Api(self.api_client)
        self.command = {
            'pvc': {
                'list': self.api_instance.list_namespaced_persistent_volume_claim,
                'get': self.api_instance.read_namespaced_persistent_volume_claim,
                'patch': self.api_instance.patch_namespaced_persistent_volume_claim,
                'create': self.api_instance.create_namespaced_persistent_volume_claim,
                'config': Conf.pvc
            },
            'cm': {
                'list': self.api_instance.list_namespaced_config_map,
                'get': self.api_instance.read_namespaced_config_map,
                'patch': self.api_instance.patch_namespaced_config_map,
                'create': self.api_instance.create_namespaced_config_map,
                'delete': self.api_instance.delete_namespaced_config_map,
                'config': Conf.cm
            },
            'svc': {
                'list': self.api_instance.list_namespaced_service,
                'get': self.api_instance.read_namespaced_service,
                'patch': self.api_instance.patch_namespaced_service,
                'create': self.api_instance.create_namespaced_service,
                'delete': self.api_instance.delete_namespaced_service,
                'config': Conf.svc
            },
            'deploy': {
                'list': client.AppsV1Api(self.api_client).list_namespaced_deployment,
                'get': client.AppsV1Api(self.api_client).read_namespaced_deployment,
                'patch': client.AppsV1Api(self.api_client).patch_namespaced_deployment,
                'create': client.AppsV1Api(self.api_client).create_namespaced_deployment,
                'delete': client.AppsV1Api(self.api_client).delete_namespaced_deployment,
                'config': Conf.deploy
            },
            'daemon_set': {
                'list': client.AppsV1Api(self.api_client).list_namespaced_daemon_set,
                'get': client.AppsV1Api(self.api_client).read_namespaced_daemon_set,
                'patch': client.AppsV1Api(self.api_client).patch_namespaced_daemon_set,
                'create': client.AppsV1Api(self.api_client).create_namespaced_daemon_set,
                'delete': client.AppsV1Api(self.api_client).delete_namespaced_daemon_set,
                'config': Conf.daemon_set
            },
            'pod': {
                'list': self.api_instance.list_namespaced_pod,
                'get': self.api_instance.read_namespaced_pod,
                'patch': self.api_instance.patch_namespaced_pod,
                'delete': self.api_instance.delete_namespaced_pod,
                'exec': client.CoreV1Api(api_client=WsApiClient(configuration)).connect_get_namespaced_pod_exec
            }
        }

    async def get(self, mode: str, name: str):
        try:
            return await self.command[mode]['get'](name, self.namespace, _request_timeout=3)
        except ApiException as e:
            if e.status == 404:
                pass
            else:
                logging.warning(e)
            return None

    async def apply(self, mode: str, name: str, **kwargs) -> bool:
        kwargs['namespace'] = self.namespace
        try:
            if await self.get(mode, name):
                await self.command[mode]['patch'](name, self.namespace, self.command[mode]['config'](name, kwargs),
                                                  _request_timeout=3)
                return True
            else:
                await self.command[mode]['create'](self.namespace, self.command[mode]['config'](name, kwargs),
                                                   _request_timeout=3)
                return True
        except ApiException as e:
            logging.warning(e)
            return False

    async def delete(self, mode: str, name: str, force: bool = False) -> bool:
        try:
            if force:
                ori = await self.command[mode]['get'](name, self.namespace, _request_timeout=3)
                if ori.metadata.finalizers:
                    del ori.metadata.finalizers
                    await self.command[mode]['patch'](name, self.namespace, ori, _request_timeout=3)
            await self.command[mode]['delete'](name, self.namespace, grace_period_seconds=0, _request_timeout=3)
            return True
        except ApiException as e:
            logging.warning(e)
            return False

    async def exec(self, pod_name: str, cmd: list) -> str:
        try:
            api_response = await self.command['pod']['exec'](pod_name, self.namespace, command=cmd, stderr=True,
                                                             stdin=False, stdout=True, tty=False, _request_timeout=3)
            return api_response
        except ApiException as e:
            logging.warning(e)
            return ''

    async def log(self, pod_name: str) -> str:
        try:
            return await self.api_instance.read_namespaced_pod_log(pod_name, self.namespace, _request_timeout=3)
        except ApiException as e:
            logging.warning(e)
            return ''

    async def pod(self, pod_name: str = '', name: str = '', ready: bool = False) -> dict | list:
        try:
            if pod_name:
                resp = await self.command['pod']['get'](pod_name, namespace=self.namespace, _request_timeout=3)
                data = {
                    'node': resp.spec.node_name,
                    'status': resp.status.phase,
                    'image': resp.status.container_statuses[0].image,
                    'ready': resp.status.container_statuses[0].ready
                }
                return data
            else:
                data = []
                if name:
                    resp = await self.command['pod']['list'](namespace=self.namespace, label_selector=f"app={name}",
                                                             timeout_seconds=3, _request_timeout=3)
                else:
                    resp = await self.command['pod']['list'](namespace=self.namespace, timeout_seconds=3,
                                                             _request_timeout=3)
                for i in resp.items:
                    if ready and not i.status.container_statuses[0].ready:
                        continue
                    data.append({
                        'name': i.metadata.name,
                        'node': i.spec.node_name,
                        'status': i.status.phase,
                        'image': i.status.container_statuses[0].image,
                        'ready': i.status.container_statuses[0].ready
                    })
                return data
        except ApiException as e:
            logging.warning(e)
            return {}

    async def top(self, pod_name: str = '') -> dict | list:
        try:
            api = f'/apis/metrics.k8s.io/v1beta1/namespaces/{self.namespace}/pods'
            if pod_name:
                ret = await self.api_client.call_api(f'{api}/{pod_name}', 'GET', _preload_content=False,
                                                     _request_timeout=3, auth_settings=self.auth_settings)
                if ret.status == 200:
                    data = (await ret.json())['containers']
                    if data:
                        return data[0]
                    else:
                        return []
                else:
                    raise ApiException
            else:
                ret = await self.api_client.call_api(api, 'GET', _preload_content=False, _request_timeout=3,
                                                     auth_settings=self.auth_settings)
                if ret.status == 200:
                    data = {i['metadata']['name']: i['containers'][0] for i in (await ret.json()['items']) if
                            i['containers']}
                    return data
                else:
                    raise ApiException
        except ApiException as e:
            logging.warning(e)
            return []

    async def config(self, name: str) -> str:
        try:
            resp = await self.command['cm']['get'](name, namespace=self.namespace, _request_timeout=3)
            return resp.data['worker.conf']
        except ApiException as e:
            logging.warning(e)
            return ''

    async def nodes(self) -> list:
        try:
            resp = await self.api_instance.list_node(timeout_seconds=3, _request_timeout=3)
            nodes = [i.metadata.labels['kubernetes.io/hostname'] for i in resp.items]
            return nodes
        except ApiException as e:
            logging.warning(e)
            return []

    async def pvc_size(self, name: str) -> str:
        try:
            resp = await self.command['pvc']['get'](name, namespace=self.namespace, _request_timeout=3)
            return resp.spec.resources.requests['storage']
        except ApiException as e:
            logging.warning(e)
            return ''

    async def deploy_node_image(self, name: str) -> (str, str):
        try:
            resp = await self.command['deploy']['get'](name, namespace=self.namespace, _request_timeout=3)
            try:
                node = resp.spec.template.spec.nodeSelector['kubernetes.io/hostname']
            except:
                node = ''
            image = resp.spec.template.spec.containers[0].image
            return node, image
        except ApiException as e:
            logging.warning(e)
            return '', ''

    async def restart(self, name: str) -> bool:
        success = True
        pods = await self.pod(name=name)
        for pod in pods:
            if not await self.delete('pod', pod['name'], force=True):
                success = False
        return success


class Tunasync(object):
    def __init__(self, api='http://127.0.0.1:14242'):
        self.api = api

    async def __requests__(self, uri, method: str = 'get', data: dict = None, ret: bool = True):
        url = self.api + uri
        async with aiohttp.ClientSession(raise_for_status=True, timeout=3) as client:
            async with client.request(method, url, json=data, timeout=3) as resp:
                res = await resp.json()
                if not ret:
                    if resp.status == 200 and 'error' not in res:
                        return True
                    else:
                        logging.warning(resp.text)
                        return False
                return res

    async def jobs(self, worker: str = '') -> list:
        if worker:
            return await self.__requests__(f'/workers/{worker}/jobs')
        return await self.__requests__('/jobs')

    async def workers(self) -> list:
        workers = await self.__requests__('/workers')
        if isinstance(workers, list):
            return workers
        else:
            return []

    async def flush_disabled(self) -> bool:
        try:
            return await self.__requests__('/jobs/disabled', method='delete', ret=False)
        except:
            return False

    async def delete_worker(self, worker: str) -> bool:
        try:
            return await self.__requests__(f'/workers/{worker}', method='delete', ret=False)
        except:
            return False

    async def set_size(self, worker: str, mirror: str, size: str) -> bool:
        data = {'Name': mirror, 'Size': size}
        try:
            return await self.__requests__(f'/workers/{worker}/jobs/{mirror}/size', method='post', data=data, ret=False)
        except:
            return False

    async def cmd(self, worker: str, cmd: str) -> bool:
        if cmd == 'reload':
            data = {'cmd': cmd, 'worker_id': worker, 'options': {"force": True}}
        else:
            data = {'cmd': cmd, 'mirror_id': worker, 'worker_id': worker, 'options': {"force": True}}
        try:
            return await self.__requests__('/cmd', method='post', data=data, ret=False)
        except:
            return False
