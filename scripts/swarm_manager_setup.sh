#!/bin/bash

# Init the swarm cluster
docker swarm init

# Create the overlay network
docker network create --driver=overlay --subnet=192.168.0.0/16 --attachable cnnnet

