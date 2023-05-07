#!/bin/bash

# Create one worker as the master node with which the pytorch distributed processing is done with 
docker run --ip 192.168.0.10 --name rank0 --network cnnnet -e RANK=0 -e WORLD_SIZE=$WORLD_SIZE -dit --rm pc2558544545/dist-cnn:0.20

# # # Distribute the rest of the workers through swarm managers as services, taking advantage of load balancing 
START=1
END=$WORLD_SIZE

for (( i=$START; i<$END; i++ )) 
do
    docker service create --name rank$i --network cnnnet --mode replicated-job -e RANK=$i -e WORLD_SIZE=$WORLD_SIZE -d pc2558544545/dist-cnn:0.20
done