#!/bin/bash

# DevOps Best Practices Repository Setup Script
# This script creates the complete repository structure and integrates existing monitoring content

set -e  # Exit on error

echo "🚀 Setting up DevOps Best Practices repository structure..."

# Create main directories
mkdir -p core/{principles,metrics,patterns}
mkdir -p tools/{docker/{basics,compose,best-practices},kubernetes/{deployments,monitoring,security},ci-cd/{gitlab,jenkins,github-actions},monitoring/{prometheus,grafana,elastic-stack},iac/{terraform,ansible,gitops}}
mkdir -p scripts/{bash,python,go/monitoring-agent}
mkdir -p industrial/{scada-integration,iot-pipelines,edge-computing,compliance/{russia,eu}}
mkdir -p templates/{docker,k8s-manifests,ci-cd-pipelines,monitoring-dashboards}
mkdir -p trends/{2025,emerging}
mkdir -p guides/{beginner,intermediate,advanced,migration}
mkdir -p career/{roadmap,interview,skills-matrix,certifications}
mkdir -p case-studies/{enterprise,startup,industrial}
mkdir -p translations/{ru,en,zh}
mkdir -p news/weekly
mkdir -p .github/{workflows,ISSUE_TEMPLATE}

# Create root files
cat > README.md << 'EOF'
# DevOps Best Practices 🚀

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg?style=flat)](CONTRIBUTING.md)

> Curated collection of production-ready DevOps best practices, scripts (Bash/Python/Go), and tools. Industrial-grade solutions for CI/CD, monitoring, and automation.

## 📚 Quick Navigation

- [Core Principles](./core/principles/) - Fundamental DevOps concepts
- [Tools & Technologies](./tools/) - Categorized tools and examples
- [Ready Scripts](./scripts/) - Copy-paste solutions
- [Industrial DevOps](./industrial/) - Enterprise and industrial solutions
- [Career Guide](./career/) - DevOps career roadmap

## 🔥 Featured Content

- [DORA Metrics Guide](./core/metrics/dora-metrics.md)
- [Production Monitoring Setup](./tools/monitoring/)
- [CI/CD Best Practices](./core/principles/ci-cd.md)
- [GitOps Implementation](./tools/iac/gitops/)

## 🛠️ Quick Start

```bash
# Clone the repository
git clone https://github.com/DevOpsBestPracticesTelegramCanal/DevOpsBestPractices.git

# Navigate to scripts
cd DevOpsBestPractices/scripts/bash

# Run example script
./docker-cleanup.sh
```

## 📊 Repository Structure

```
DevOpsBestPractices/
├── 📚 core/           # Fundamental best practices
├── 🔧 tools/          # Tools by category
├── 📦 scripts/        # Ready-to-use scripts
├── 🏭 industrial/     # Industrial DevOps
├── 🚀 templates/      # Production templates
├── 📈 trends/         # Current trends
├── 📖 guides/         # Step-by-step guides
├── 💼 career/         # Career resources
└── 📊 case-studies/   # Real-world examples
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

## 📰 Stay Updated

- 📱 [Telegram Channel](https://t.me/devops_best_practices)
- 📝 [Weekly Newsletter](./news/weekly/)

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---
⭐ Star this repository if you find it helpful!
EOF

cat > CONTRIBUTING.md << 'EOF'
# Contributing to DevOps Best Practices

Thank you for your interest in contributing! This document provides guidelines for contributions.

## How to Contribute

1. **Fork the repository**
2. **Create a feature branch** (`git checkout -b feature/amazing-feature`)
3. **Commit your changes** (`git commit -m 'Add amazing feature'`)
4. **Push to the branch** (`git push origin feature/amazing-feature`)
5. **Open a Pull Request**

## Contribution Guidelines

### Code Quality
- Follow existing code style
- Add comments for complex logic
- Test your scripts before submitting

### Documentation
- Update README.md if needed
- Add examples for new features
- Keep documentation clear and concise

### Commit Messages
- Use clear and meaningful commit messages
- Start with a verb (Add, Fix, Update, Remove)
- Reference issues when applicable

## Code of Conduct

Be respectful and inclusive. We welcome contributors from all backgrounds.

## Questions?

Feel free to open an issue or contact us via [Telegram](https://t.me/devops_best_practices).
EOF

cat > LICENSE << 'EOF'
MIT License

Copyright (c) 2025 DevOps Best Practices

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
EOF

# Create core/principles files
cat > core/principles/automation.md << 'EOF'
# Automation Best Practices

## Overview
Automation is the cornerstone of DevOps, reducing manual work and human error.

## Key Principles
1. **Automate Everything**: From testing to deployment
2. **Idempotency**: Ensure scripts can run multiple times safely
3. **Version Control**: All automation scripts in Git
4. **Documentation**: Clear documentation for all automated processes

## Tools
- Ansible
- Terraform
- Jenkins
- GitHub Actions
EOF

cat > core/principles/ci-cd.md << 'EOF'
# CI/CD Best Practices

## Continuous Integration
- Commit code frequently
- Automated testing on every commit
- Fast feedback loops

## Continuous Delivery
- Automated deployment pipelines
- Environment consistency
- Rollback capabilities
EOF

cat > core/principles/monitoring.md << 'EOF'
# Monitoring Best Practices

## Key Metrics
- DORA metrics
- Business KPIs
- System health indicators

## Tools
- Prometheus
- Grafana
- ELK Stack

## Alerting
- Define SLIs/SLOs
- Actionable alerts only
- Escalation policies
EOF

# Create sample scripts
cat > scripts/bash/docker-cleanup.sh << 'EOF'
#!/bin/bash
# Docker Cleanup Script
# Removes unused containers, images, and volumes

echo "🧹 Starting Docker cleanup..."

# Remove stopped containers
docker container prune -f

# Remove unused images
docker image prune -a -f

# Remove unused volumes
docker volume prune -f

# Remove unused networks
docker network prune -f

echo "✅ Docker cleanup completed!"
EOF

chmod +x scripts/bash/docker-cleanup.sh

cat > scripts/python/metrics-collector.py << 'EOF'
#!/usr/bin/env python3
"""
Simple metrics collector example
"""

import psutil
import json
from datetime import datetime

def collect_metrics():
    """Collect system metrics"""
    metrics = {
        "timestamp": datetime.now().isoformat(),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory": psutil.virtual_memory()._asdict(),
        "disk": psutil.disk_usage('/')._asdict()
    }
    return metrics

if __name__ == "__main__":
    metrics = collect_metrics()
    print(json.dumps(metrics, indent=2))
EOF

# Create GitHub Actions workflow
cat > .github/workflows/validate-scripts.yml << 'EOF'
name: Validate Scripts

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v2
    
    - name: Validate Bash Scripts
      run: |
        for script in scripts/bash/*.sh; do
          bash -n "$script"
        done
    
    - name: Validate Python Scripts
      run: |
        python -m py_compile scripts/python/*.py
EOF

# Create trends documentation
cat > trends/2025/aiops.md << 'EOF'
# AIOps in 2025

## Overview
AI/ML integration in DevOps for intelligent automation and predictive analytics.

## Key Areas
- Anomaly detection
- Predictive maintenance
- Auto-remediation
- Intelligent alerting

## Tools
- Dynatrace
- Datadog
- New Relic
EOF

# Integrate existing monitoring content
echo "📁 Integrating existing monitoring content..."

# Check if monitoring directory exists in current repo
if [ -d "monitoring" ]; then
    echo "Found existing monitoring directory. Integrating..."
    
    # Move Grafana content
    if [ -d "monitoring/grafana-enterprise" ]; then
        cp -r monitoring/grafana-enterprise/* tools/monitoring/grafana/ 2>/dev/null || true
        echo "✅ Grafana content integrated"
    fi
    
    # Move Prometheus content
    if [ -d "monitoring/grafana-enterprise/prometheus" ]; then
        cp -r monitoring/grafana-enterprise/prometheus/* tools/monitoring/prometheus/ 2>/dev/null || true
        echo "✅ Prometheus content integrated"
    fi
    
    # Copy any README or documentation
    if [ -f "monitoring/README.md" ]; then
        cp monitoring/README.md tools/monitoring/README.md
    fi
    
    # Archive original monitoring directory
    mv monitoring monitoring_backup_$(date +%Y%m%d_%H%M%S)
    echo "📦 Original monitoring directory backed up"
else
    echo "⚠️ No existing monitoring directory found. Creating example content..."
    
    # Create example monitoring content
    cat > tools/monitoring/README.md << 'EOF'
# Monitoring Tools

This section contains best practices and configurations for monitoring tools.

## Prometheus
Enterprise-grade monitoring and alerting toolkit.

## Grafana
Visualization and analytics platform.

## Elastic Stack
Log aggregation and analysis.
EOF
fi

# Create a setup completion marker
cat > .setup_complete << 'EOF'
Repository structure created successfully!
Timestamp: $(date)
EOF

echo "
✅ Repository structure created successfully!

Next steps:
1. Review the created structure
2. Add your specific content to each section
3. Customize templates and scripts
4. Set up GitHub Actions secrets if needed
5. Update README.md with your specific information

📁 Structure created:
- Core principles and patterns
- Tools configurations
- Ready-to-use scripts
- Industrial DevOps section
- Career resources
- Documentation

🔄 Monitoring content has been integrated into tools/monitoring/

Happy DevOps! 🚀
"
