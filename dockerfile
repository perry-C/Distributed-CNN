FROM pytorch/pytorch

# Add ubuntu user and enable password-less sudo
RUN useradd -mU -s /bin/bash -G sudo ubuntu && \
    echo "ubuntu ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

COPY . .

ENV PYTHONUNBUFFERED=1

RUN apt-get update
RUN apt install -y nano vim net-tools psmisc nmap


CMD [ "python3", "src/main.py" ]       