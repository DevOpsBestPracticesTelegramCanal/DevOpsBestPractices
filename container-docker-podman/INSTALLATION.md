# 📥 Container-Docker-Podman Installation Guide

Comprehensive setup guide for all container technologies covered in this section.

## 🎯 Quick Start

### Prerequisites Check
```bash
# System requirements
uname -a                    # Linux kernel 3.10+
docker --version           # Docker 24.0+
podman --version           # Podman 4.0+
kubectl version --client   # Kubernetes client
```

### One-Command Setup
```bash
# Complete environment setup
curl -s https://raw.githubusercontent.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices/main/scripts/container-stack-install.sh | bash
```

## 🐳 Traditional Stack Installation

### Docker Engine
```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Enable non-root access
newgrp docker

# Verify installation
docker run hello-world
```

### Podman Setup
```bash
# Ubuntu 22.04+
sudo apt update
sudo apt install podman podman-compose

# RHEL/CentOS/Fedora
sudo dnf install podman podman-compose

# Enable systemd service
systemctl --user enable podman.socket
systemctl --user start podman.socket

# Test rootless containers
podman run --rm hello-world
```

### Docker Compose Alternative
```bash
# Use podman-compose as drop-in replacement
alias docker-compose='podman-compose'

# Or use Podman native compose
podman compose --help
```

## 🚀 Next-Generation Stack

### WebAssembly Runtime
```bash
# Install WasmEdge
curl -sSf https://raw.githubusercontent.com/WasmEdge/WasmEdge/master/utils/install.sh | bash
source ~/.bashrc

# Install Wasmtime
curl https://wasmtime.dev/install.sh -sSf | bash

# Docker WASM support
docker buildx create --use --name wasm-builder --driver-opt env.BUILDKIT_EXPERIMENTAL=1
```

### Firecracker MicroVMs
```bash
# Install Firecracker
release_url="https://github.com/firecracker-microvm/firecracker/releases"
latest=$(basename $(curl -fsSLI -o /dev/null -w  %{url_effective} ${release_url}/latest))
arch=`uname -m`
curl -L ${release_url}/download/${latest}/firecracker-${latest}-${arch}.tgz \
  | tar -xz --directory /tmp
sudo mv /tmp/release-${latest}/firecracker-${latest} /usr/local/bin/firecracker

# Install Jailer
sudo mv /tmp/release-${latest}/jailer-${latest} /usr/local/bin/jailer
```

### eBPF Tools
```bash
# Install BCC tools
sudo apt install bpfcc-tools linux-headers-$(uname -r)

# Install bpftrace
sudo apt install bpftrace

# Verify eBPF support
sudo bpftrace -e 'BEGIN { printf("eBPF is working!\n"); exit(); }'
```

## 🌐 Edge-Native Setup

### K3s Installation
```bash
# Master node installation
curl -sfL https://get.k3s.io | sh -

# Get node token
sudo cat /var/lib/rancher/k3s/server/node-token

# Worker node join
curl -sfL https://get.k3s.io | K3S_URL=https://master-ip:6443 \
  K3S_TOKEN=your-token sh -

# Configure kubectl
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
```

### KubeEdge Setup
```bash
# Install keadm
wget https://github.com/kubeedge/kubeedge/releases/download/v1.15.0/keadm-v1.15.0-linux-amd64.tar.gz
tar -xzf keadm-v1.15.0-linux-amd64.tar.gz
sudo cp keadm /usr/local/bin/

# Initialize cloud core
sudo keadm init --advertise-address="CLOUD_CORE_IP"

# Join edge node
sudo keadm join --cloudcore-ipport="CLOUD_CORE_IP:10000" --token=TOKEN
```

## 🤖 AI/ML Stack

### NVIDIA Container Runtime
```bash
# Add NVIDIA Docker repository
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# Install NVIDIA Container Runtime
sudo apt update
sudo apt install nvidia-container-runtime

# Configure Docker
sudo tee /etc/docker/daemon.json <<EOF
{
    "default-runtime": "nvidia",
    "runtimes": {
        "nvidia": {
            "path": "nvidia-container-runtime",
            "runtimeArgs": []
        }
    }
}
EOF

sudo systemctl restart docker
```

### Kubeflow Installation
```bash
# Install kustomize
curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
sudo mv kustomize /usr/local/bin/

# Install Kubeflow
git clone https://github.com/kubeflow/manifests.git
cd manifests
while ! kustomize build example | kubectl apply -f -; do echo "Retrying to apply resources"; sleep 10; done
```

## 🔒 Security Stack

### Falco Installation
```bash
# Add Falco repository
curl -s https://falco.org/repo/falcosecurity-packages.asc | sudo apt-key add -
echo "deb https://download.falco.org/packages/deb stable main" | sudo tee -a /etc/apt/sources.list.d/falcosecurity.list

# Install Falco
sudo apt update
sudo apt install falco

# Start and enable
sudo systemctl enable falco
sudo systemctl start falco
```

### Cosign for Image Signing
```bash
# Install Cosign
wget https://github.com/sigstore/cosign/releases/download/v2.2.1/cosign-linux-amd64
sudo mv cosign-linux-amd64 /usr/local/bin/cosign
sudo chmod +x /usr/local/bin/cosign

# Generate key pair
cosign generate-key-pair

# Sign container image
cosign sign --key cosign.key myregistry/myimage:tag
```

### OPA Gatekeeper
```bash
# Install Gatekeeper
kubectl apply -f https://raw.githubusercontent.com/open-policy-agent/gatekeeper/release-3.14/deploy/gatekeeper.yaml

# Verify installation
kubectl get pods -n gatekeeper-system
```

## 📊 Monitoring Stack

### Prometheus + Grafana
```bash
# Install using Helm
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install kube-prometheus-stack
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace

# Access Grafana
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
```

### GPU Monitoring
```bash
# Install DCGM Exporter
helm repo add gpu-helm-charts https://nvidia.github.io/dcgm-exporter/helm-charts
helm install dcgm-exporter gpu-helm-charts/dcgm-exporter \
  --namespace gpu-monitoring --create-namespace
```

## ✅ Verification Scripts

### Complete Stack Test
```bash
#!/bin/bash
# verify-installation.sh

echo "🔍 Verifying Container Stack Installation..."

# Test Docker
docker run --rm hello-world && echo "✅ Docker OK" || echo "❌ Docker Failed"

# Test Podman
podman run --rm hello-world && echo "✅ Podman OK" || echo "❌ Podman Failed"

# Test Kubernetes
kubectl cluster-info && echo "✅ Kubernetes OK" || echo "❌ Kubernetes Failed"

# Test GPU (if available)
if command -v nvidia-smi &> /dev/null; then
    docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu20.04 nvidia-smi && echo "✅ GPU Support OK"
fi

# Test WebAssembly
if command -v wasmtime &> /dev/null; then
    echo '(module (func (export "main") (result i32) i32.const 42))' | wasmtime --invoke main - && echo "✅ WASM OK"
fi

echo "🎉 Installation verification complete!"
```

## 🔧 Troubleshooting

### Common Issues

#### Docker Permission Denied
```bash
sudo usermod -aG docker $USER
newgrp docker
```

#### Podman Rootless Issues
```bash
# Check user namespaces
cat /proc/sys/user/max_user_namespaces

# If zero, enable user namespaces
echo 'user.max_user_namespaces = 28633' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

#### Kubernetes Node Not Ready
```bash
# Check node status
kubectl describe node

# Common fixes
sudo systemctl restart kubelet
sudo systemctl restart docker
```

#### GPU Not Detected
```bash
# Check NVIDIA driver
nvidia-smi

# Reinstall NVIDIA runtime
sudo apt purge nvidia-container-runtime
sudo apt install nvidia-container-runtime
sudo systemctl restart docker
```

## 📋 System Requirements

### Minimum Requirements
- **OS**: Ubuntu 20.04+, RHEL 8+, or compatible
- **RAM**: 4GB (8GB recommended)
- **CPU**: 2 cores (4+ recommended)
- **Storage**: 20GB free space
- **Network**: Internet access for downloads

### Recommended Hardware
- **RAM**: 16GB+ for AI/ML workloads
- **CPU**: 8+ cores for production
- **GPU**: NVIDIA Tesla/RTX for AI workloads
- **Storage**: NVMe SSD for performance
- **Network**: 1Gbps+ for distributed workloads

## 🎯 Next Steps

After installation:
1. Review [Traditional Containers](./traditional/) for basics
2. Explore [Next-Generation](./next-generation/) technologies
3. Set up [Security-First](./security-first/) practices
4. Configure [Monitoring](./observability/) stack
5. Plan [Production](./production/) deployment