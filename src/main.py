import os
import torch
import math
import logging
import torch.distributed as dist
import torch.multiprocessing as mp
from torch import optim
from torch.nn import functional as F
from torchvision import transforms
from partitioner import DataPartitioner
from shallow_cnn import SHA_CNN
from datetime import timedelta
import time
import numpy as np
from typing import Union
import dataset


if torch.cuda.is_available():
    print("I know my gpu works")
    DEVICE = torch.device("cuda")
else:
    print("I know my cpu works")
    DEVICE = torch.device("cpu")

""" Initialize the distributed environment. """


def init_process(rank, size, fn, master_ip_addr, master_port, backend='gloo'):
    os.environ['MASTER_ADDR'] = master_ip_addr
    # Be sure to open this port
    # On ubuntu "sudo ufw allow 4000"
    os.environ['MASTER_PORT'] = str(master_port)
    dist.init_process_group(backend=backend, rank=rank, world_size=size)

    fn(rank, size)


""" Partitioning MNIST """


def partition_dataset():

    train_dataset = dataset.GTZAN("data/train.pkl")
    size = dist.get_world_size()
    bsz = int(128 / float(size))
    partition_sizes = [1.0 / size for _ in range(size)]
    partition = DataPartitioner(train_dataset, partition_sizes)
    partition = partition.use(dist.get_rank())
    train_set = torch.utils.data.DataLoader(partition,
                                            batch_size=bsz,
                                            shuffle=True)
    return train_set, bsz


""" Distributed Synchronous SGD Example """


def run(rank, size):
    torch.manual_seed(1234)
    train_set, bsz = partition_dataset()
    model = SHA_CNN().to(DEVICE)
    optimizer = optim.SGD(model.parameters(),
                          lr=0.01, momentum=0.5)

    num_batches = math.ceil(len(train_set.dataset) / float(bsz))
    ep_count = 0
    escalated_time = 0.0
    for epoch in range(10):
        data_load_start_time = time.time()
        epoch_loss = 0.0
        b_count = 0
        for _, batch, labels, _ in train_set:
            data_load_end_time = time.time()
            batch = batch.to(DEVICE)
            labels = labels.to(DEVICE)

            CHECKPOINT_PATH = f"src/checkpoints/checkpoint_ep{ep_count}_b{b_count}"

            torch.save(model.state_dict(), CHECKPOINT_PATH)

            # Use a barrier() to make sure that process 1 loads the model after process
            # 0 saves it.
            dist.barrier()
            model.load_state_dict(
                torch.load(CHECKPOINT_PATH))

            b_count += 1
            optimizer.zero_grad()
            logits = model(batch)
            loss = F.nll_loss(logits, labels)
            epoch_loss += loss.item()
            loss.backward()
            average_gradients(model)
            optimizer.step()

            with torch.no_grad():
                preds = logits.argmax(-1)
                accuracy = compute_accuracy(labels, preds)

            data_load_time = data_load_end_time - data_load_start_time
            step_time = time.time() - data_load_end_time
            escalated_time += data_load_time + step_time
            print(f"epoch: [{epoch}], "
                  f"batch accuracy: {accuracy * 100:2.2f}, "
                  f"step time: {step_time:.5f}, "
                  f"data load time: {escalated_time:.5f}"
                  )
            data_load_start_time = time.time()

        ep_count += 1

        print("")
        print(f'Rank {dist.get_rank()}, ',
              f'epoch: {epoch}, ',
              f"epoch_loss: {epoch_loss / num_batches}, ",
              f"Escalated time:{escalated_time}")
        print("")

    cleanup()


""" Gradient averaging. """


def average_gradients(model):

    size = float(dist.get_world_size())
    for param in model.parameters():
        handle = dist.all_reduce(
            param.grad.data, op=dist.ReduceOp.SUM, async_op=True)
        handle.wait()
        handle.is_completed()
        param.grad.data /= size


def compute_accuracy(
        labels: Union[torch.Tensor, np.ndarray], preds: Union[torch.Tensor, np.ndarray]
) -> float:
    """
    Args:
            labels: ``(batch_size, class_count)`` tensor or array containing example labels
            preds: ``(batch_size, class_count)`` tensor or array containing model prediction
    """
    assert len(labels) == len(preds)
    return float((labels == preds).sum()) / len(labels)


def cleanup():
    dist.destroy_process_group()


if __name__ == "__main__":

    print(f"torch.dist status is {torch.distributed.is_available()}")

    # Pass in env vars from cmd
    world_size = int(os.environ.get("WORLD_SIZE"))

    # Fixed ip address for the master node,
    # that is shared among all worker nodes for syncing gradients
    master_ip_addr = "192.168.0.10"

    rank = int(os.environ.get("RANK"))

    master_port = 7946

    # processes = []
    # Needs to be a shared queue
    # So every instance joined will check this
    # And make itself the rank = process.size()

    mp.set_start_method("spawn")

    print("rank:" + str(rank) + "(worker)")

    p = mp.Process(target=init_process, args=(rank, world_size,
                                              run, master_ip_addr, master_port))

    p.start()
    p.join()
