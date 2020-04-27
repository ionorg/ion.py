# ion.py

ion.py provides a python interface for creating python microservices that integrate into the ion architecture.

## Install

```
pip install ion.py
```

## Usage

```toml
dc = "dc1"

[etcd]
addrs = ["etcd:2379"]

[nats]
url = "nats://nats:4222"
```

```python
import asyncio
from ion import Service

def run(config, loop):
    # Create service
    service = await Service.create(config["nats"]["url"], config["etcd"]["addrs"], config["dc"], loop=loop)

    # Register service node
    service.register("python-service", "node-python-service")

    # Watch a service
    service.watch(["islb"])

    async def handler(msg):
        # do stuff

        # broadcast a message to clients over islb
        await service.request("islb", "broadcast", {
            "rid": rid,
            "info": {
                ...
            }
        })

    # Subsribe to a message on NATS
    await service.subscribe("topic", handler)

loop = asyncio.get_event_loop()
loop.run_until_complete(run(config, loop))
try:
    loop.run_forever()
finally:
    loop.close()
```
