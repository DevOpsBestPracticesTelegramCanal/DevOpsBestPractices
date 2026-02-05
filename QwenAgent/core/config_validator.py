# -*- coding: utf-8 -*-
"""Configuration Validator Module"""

import os
from typing import Dict, List
import re

class ConfigValidator:
    """Validates configuration dictionary."""
    
    REQUIRED_FIELDS = ['ollama_url', 'fast_model', 'heavy_model', 'project_root']
    
    def __init__(self, config: dict):
        self.config = config
    
    def validate(self) -> Dict:
        """Validate configuration and return result."""
        errors = []
        warnings = []
        
        for field in self.REQUIRED_FIELDS:
            if field not in self.config:
                errors.append(f'Required field not found: {field}')
            elif not self.config[field]:
                errors.append(f'Empty required field: {field}')
        
        # Validate URL format
        if 'ollama_url' in self.config:
            if not self.validate_url(self.config['ollama_url']):
                errors.append('Invalid ollama_url format')

        # Validate project_root exists
        if 'project_root' in self.config and self.config['project_root']:
            path = os.path.expanduser(self.config['project_root'])
            if not os.path.isdir(path):
                warnings.append(f'Directory does not exist: {path}')

        return {'valid': len(errors) == 0, 'errors': errors, 'warnings': warnings}
    
    def validate_url(self, url: str) -> bool:
        """Check if URL is valid."""
        pattern = r'^https?://[\w.-]+(:\d+)?(/.*)?$'
        return bool(re.match(pattern, url))