import asyncio
import etcd3
import json
import string
import uuid
import netifaces as ni
import random
import os
from collections import defaultdict
from nats.aio.client import Client as NATS
from nats.aio.errors import ErrTimeout

GRANT_TIMEOUT = 5


class Registry:
    def __init__(self, endpoints, scheme):
        host, port = endpoints[0].split(":")
        self.scheme = scheme
        self.client = etcd3.client(host=host, port=int(port))

    def get_service_path(self, name):
        return os.path.join(self.scheme, name.replace("/", "-"))

    def register(self, node):
        key = "%s%s" % (self.scheme, node.id)
        lease = self.client.lease(GRANT_TIMEOUT)
        self.client.put(key, node.json(), lease)

        @asyncio.coroutine
        def periodic():
            while True:
                lease.refresh()
                yield from asyncio.sleep(GRANT_TIMEOUT - 1)

        loop = asyncio.get_event_loop()
        loop.create_task(periodic())

    def get(self, service_name):
        nodes = []
        for v, _ in self.client.get_prefix(self.get_service_path(service_name)):
            nodes.append(json.loads(v))
        return nodes

    def watch(self, service_name, callback):
        self.client.add_watch_prefix_callback(
            self.get_service_path(service_name), callback)


class RPCChannel:
    def __init__(self, nc, name):
        self.name = name
        self.nc = nc

    async def request(self, method, data):
        payload = {
            "request": True,
            "id":      random.randint(1000000, 9999999),
            "method":  method,
            "data":    data,
        }

        try:
            response = await self.nc.request(self.name, json.dumps(payload).encode())
            return response
        except ErrTimeout:
            print("Request timed out")


class Node:
    def __init__(self, nc, service, name, id):
        self.service = service
        self.name = name
        self.id = id
        ni.ifaddresses('eth0')
        ip = ni.ifaddresses('eth0')[ni.AF_INET][0]['addr']
        self.ip = ip
        self.rpc = RPCChannel(nc, "rpc-%s" % (self.id))

    def get_event_channel(self):
        return "event-%s" % (self.id)

    def json(self):
        return json.dumps({
            "id": self.id,
            "ip": self.ip,
            "name": self.name,
            "service": self.service,
        })


class Service:
    @classmethod
    async def create(cls, nats_url, etcd_endpoints, datacenter, loop=None):
        self = Service(etcd_endpoints, datacenter)
        self.nc = NATS()
        await self.nc.connect(nats_url, loop=loop)
        self.watcher = Watcher(self.nc, etcd_endpoints, datacenter)
        return self

    def __init__(self, etcd_endpoints, datacenter):
        self.registry = Registry(etcd_endpoints, "/%s/node/" % datacenter)
        self.node = None

    def register(self, service_name, name):
        self.node = Node(self.nc, service_name, name, "%s-%s" %
                         (service_name, random_string(12)))

        self.registry.register(self.node)

    def watch(self, service_names):
        for service in service_names:
            self.watcher.watch(service)

    async def subscribe(self, subject, callback):
        await self.nc.subscribe("broadcaster", cb=callback)

    async def request(self, service_name, method, data):
        service = self.watcher.get(service_name)
        return await service.rpc.request(method, data)


class Watcher:
    def __init__(self, nc, etcd_endpoints, datacenter):
        self.nc = nc
        self.registry = Registry(etcd_endpoints, "/%s/node/" % datacenter)
        self.nodes = defaultdict(dict)

    def watch(self, service_name):
        nodes = self.registry.get(service_name)
        for node in nodes:
            self.nodes[node["service"]][node["id"]] = Node(
                self.nc, node["service"], node["name"], node["id"])

        # self.registry.watch(service_name) TODO: Watch for changes

    def get(self, service_name):
        return next(iter(self.nodes[service_name].values()))


def random_string(n):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))
