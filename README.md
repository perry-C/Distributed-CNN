# Distributed-CNN
## Architecture diagram
![architecture_diagram drawio](https://github.com/perry-C/Distributed-CNN/assets/55983397/94cb19ff-5abb-47b2-a6c4-003229b6c446)

## Instructions for deployment
if using aws academy: 
- Update the **~/.aws/credentials** file to up-to-date version for the current session 

- the main implementation is a pytorch-based distributed Convolutional-Neural-Net which runs on the amount of ec2 instances defined by the environmental variable **WORLD_SIZE**(which is the only user-parameters provided for tunning)
    ```bash
    # Setup the environment
    
    # Extremely important, defines the number of ec2 instances to be made / the number of containers that we train the model on  

    export WORLD_SIZE=(int) # 1-5 is ideal as setting it too high would reach cpu request limit 
    
    chmod -R u+x scripts

    # Inside "fabfile.env", change these variables to:
    ssh_key_path = "PATHTOKEY/KEYNAME.pem"
    key_name = "KEYNAME"
   
    
    # Set up the swarm clusters
    fab start # May take a while to pull the docker file
    fab setupmaster 
    
    # Note: This step can be skipped if world size = 1
    fab setupworkers
    
    # Finally
    fab distributejobs
    ```
- to see performance/output of the training process (after all the commands above has been run):
    ```bash
    # rank0 being the name for the master node where the swarm manager resides
    fab ec2ssh rank0
    docker attach rank0
    ```

