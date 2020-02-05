# gRPC error 14


In this document I show my researches on the gRPC error 14 following the issue [77](https://github.com/SubstraFoundation/substra-backend/issues/77)

**gRPC error code 14** can be a (non exhaustive) `14: DNS Resolution failed` or `14: UNAVAILABLE: failed to connect to all addresses` error.  
Roughly equivalent to a HTTP 503 error.

<br/><br/>

We can see its definition in the **gRPC** [code](https://github.com/grpc/grpc/blob/master/include/grpc/impl/codegen/status.h#L141):
```
  /** The service is currently unavailable.  This is a most likely a
     transient condition and may be corrected by retrying with
     a backoff. Note that it is not always safe to retry non-idempotent
     operations.
     WARNING: Although data MIGHT not have been transmitted when this
     status occurs, there is NOT A GUARANTEE that the server has not seen
     anything. So in general it is unsafe to retry on this status code
     if the call is non-idempotent.
     See litmus test above for deciding between FAILED_PRECONDITION,
     ABORTED, and UNAVAILABLE. */
  GRPC_STATUS_UNAVAILABLE = 14,
```
<br/><br/>

## gRPC definition

For understanding this error, one first need to understand how gRPC [works in the first place](https://grpc.io/docs/guides/).  
```
In gRPC a client application can directly call methods on a server application
on a different machine as if it was a local object, making it easier for you
to create distributed applications and services. As in many RPC systems, gRPC
is based around the idea of defining a service, specifying the methods that
can be called remotely with their parameters and return types. On the server
side, the server implements this interface and runs a gRPC server to handle
client calls. On the client side, the client has a stub (referred to as just
a client in some languages) that provides the same methods as the server.
```

In Hyperledger Fabric, the peer will behaves as a broker and the fabric sdk as a worker.  
If the broker goes away after the worker has taken a job, the worker throws `Error: 14 UNAVAILABLE` when it attempts to complete the job.  
No automatic retry.

<br/>

##### Ways the broker could go away/be unavailable:

- Broker address misconfigured.
- Transient network failure.
- Broker under excessive load.

###### Broker Address Misconfigured
This is an unrecoverable hard failure. Retries will not fix this.

###### Transient network failure
Some temporary disruption in connectivity between worker and broker. This could include a broker restarting or (potentially) a change in DNS (have to test this).
A retry will deal with this case if the transient network failure is fixed before the retries timeout.

###### Broker is under excessive load and cannot respond
In this case, retries may actually make it worse. Server can be driven it to failure on a single node by pumping in a massive number of workloads when it is memory starved or runs out of disk space. Having automated retries will not recover any of these situations.

If the broker is experiencing excessive load because of a traffic spike, then automated retries may drive it to failure, whereas workers failing to complete tasks once and letting the broker reschedule them may allow the broker to recover.


##### Conclusions
It is not sure automatic retry is (a) necessary; (b) a good idea.

The transient network failure seems to be the only case. I’m not sure how much of an issue that is in an actual system, and if it warrants complicating the code, or the potential downside of hammering a broker when it is experiencing excessive load (which will be either ineffective if it is a hard failure, and could contribute to a hard failure if it is a spike).


### Experimentations

I've experimented a lot of different configurations for firstly, being able to reproduce the error and secondly, find a way to fix it. 

##### 1 experimentation : local with last updates

I recreated a demo environment with 4 organizations and used the `substra-tests` project for trying to reproduce the error.  
This setup recreate ssl gRPC channel and can be easily debuggable.

Branches are:  
- hlf-k8s#test-grpc-failure
- substra-backend#test-grpc-failure
- substra-tests#test-grpc-failure

I launch hlf-k8s with docker-compose setup on 4 organizations.
```bash
$> ./python-scripts/start.py --no-backup --config ./conf/4orgs.py
```
Once done, I launch substra-backend setup locally (no docker-compose, see README) on 4 organizations.  
Then I launch the substra-tests:
```bash
$> SUBSTRA_TESTS_CONFIG_FILEPATH=demo.yaml pytest -k test_load_aggregatetuples_manual
```

I have not been able to trigger the error.  
Tests broke on the 7049 round. My disk space saturated after taking more than 365Go. 
Ram did not 

##### 2 experimentation: local with no channel closing

I did the same thing without the fix on gRPC channel closing.  
I have not been able to trigger the error.  
My RAM quickly grew and was full after 30 minutes.

##### 3 experimentation: demo environment

By being unsuccessful triggering the error, I tried on the demo, but was unable too...  
The retry process do its job.  
I could only see some logs about it.

##### 4 experimentation: local with manual interruption 

I decided to manually triggering the error.  
After all this issue could happen on transient network failure, and we cannot fix this.  
We have to be resilient on it and handle it.  
As we have an idempotent - i.e. it is safe to retry it - environment, implementing a granular retry is the best thing to do.  

Currently, when we get this error, we retry on the whole process which is not optimized.  
For example, if we send endorsing proposals to 4 orgs and one gRPC broker is unavailable, we will get a gRPC error status code 14, but the other 3 will be successful.  
In this case, we retry on the whole process aka sending 4 proposals. But we should only retry on the failed one.  

Knowing how much times to retry and delays between these retries is up to the application.  
In our case using a 15 retries delayed by 1 second could be a good setup, As the peer pods are very quick for respawning but these parameters should be heavily tested.    

We currently use the high level method of `fabric-sdk-py` for invoking the chaincode. This method can and should be always customized to the need of each application. In the first place, this method should not belong to the SDK  
I modified it for handling a retry on failed proposals and avoiding at must gRPC 14 errors.

Modified code can be found [here](https://github.com/hyperledger/fabric-sdk-py/pull/18).

For testing, I launch a hlf-k8s setup with docker-compose, Then I simply launch a substra-backend server.
In this case the clb server.  
<span style="color: red;font-weight: bold">BUT</span> I place a breakpoint on this [line](https://github.com/hyperledger/fabric-sdk-py/pull/18/files#diff-d627d0a212052fa058ddb5ef73df231eR1641) inside the python modules of my virtual environment.  
Obviously the fabric-sdk-py code has been modified.  
Here is the **MAGIC** trick!

After launching the server with:
```bash
$> BACKEND_ORG=clb BACKEND_DEFAULT_PORT=8002 BACKEND_PEER_PORT_EXTERNAL={"peer1-owkin": 7051, "peer2-owkin": 8051, "peer1-chu-nantes": 9051, "peer2-chu-nantes": 10051,  "peer1-org4": 13051, "peer2-org4": 14051} DJANGO_SETTINGS_MODULE=backend.settings.server.dev ./manage.py runserver 8002
```
I wait for the breakpoint to be reached.  
I then kill two important peers:
```bash
$> docker stop peer1-owkin peer1-org4
```

Wait for stopping.
I resume the program and quickly spawn the peers with these commands (depending where your dockerfiles folder lives):

```bash
$> docker-compose -f /datadisk/substra/dockerfiles/docker-compose-owkin.yaml up -d
$> docker-compose -f /datadisk/substra/dockerfiles/docker-compose-org4.yaml up -d
```

If you correctly set your logger, you should see in the console:
```bash
Retry on failed proposal responses
Retrying getting proposal responses from peers: ['org4MSP', 'owkinMSP'], retry: 0
Retry in 3000ms
Retrying getting proposal responses from peers: ['org4MSP', 'owkinMSP'], retry: 1
Retry in 3000ms
Retrying getting proposal responses from peers: ['org4MSP', 'owkinMSP'], retry: 2
Retry in 3000ms
Retrying getting proposal responses from peers: ['org4MSP'], retry: 3
INFO - 2020-02-05 16:23:51,381 - substrapp.ledger_utils - smartcontract invoke:registerNode; elaps=61408.94ms; error=None
```

We get no errors at the end, and the retries correctly succeeded although we stopped the availability of some of our peers.   
This retry is far more optimized and powerful than the one we are actually using.  
This will not send uneeded requests and won't take double python memory.


## Conclusion

We should definitively handle the chaincode invoke method directly in our app, as it can be different for every app in the wild.  
Furthermore this kind of strategy is very different regarding the endorsment policy of the app.  
With a basic `OR` policy, we should not even retry on failed proposal responses and simply feed the orderer with good ones.  
It can be the same for `MAJORITY` policy, but as precedently said, it depends for every app.

I hope this handling will allow us to be way much faster than we are today.  
Everything is about communication in distributed systems here and its handling.  


<br/><br/>

Thanks for reading,

<br/><br/>

#### References:

  
https://www.gitmemory.com/issue/wbobeirne/lightning-app-tutorial/1/497542924  
https://forum.zeebe.io/t/is-grpc-a-point-of-failure-when-embedding-the-workflow-in-a-program/455/14  
https://github.com/creditsenseau/zeebe-client-node-js/pull/41  
https://github.com/grpc/grpc-node/issues/692  
https://github.com/googleapis/google-cloud-node/issues/2438  
https://github.com/dgraph-io/dgraph-js/issues/50  
https://bugs.python.org/issue31452  
https://grpc.io/docs/quickstart/python/  
https://grpc.io/docs/guides/concepts/  
https://github.com/hubo1016/aiogrpc  
https://docs.python.org/3/library/asyncio-task.html  
https://thenewstack.io/5-workflow-automation-use-cases-you-might-not-have-considered/
