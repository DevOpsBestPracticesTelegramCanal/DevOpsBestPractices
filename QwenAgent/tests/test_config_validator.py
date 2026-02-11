"""Tests for ConfigValidator."""
import pytest
from core.config_validator import ConfigValidator

def test_valid_config():
    """Test with all required fields."""
    config = {
        'ollama_url': 'http://localhost:11434',
        'fast_model': 'qwen2.5-coder:3b',
        'heavy_model': 'qwen2.5-coder:7b',
        'project_root': '.'
    }
    v = ConfigValidator(config)
    result = v.validate()
    assert result['valid'] == True
    assert result['errors'] == []

def test_missing_fields():
    """Test with empty config."""
    v = ConfigValidator({})
    result = v.validate()
    assert result['valid'] == False
    assert len(result['errors']) == 4

def test_invalid_url():
    """Test with invalid URL format."""
    config = {
        'ollama_url': 'not-a-valid-url',
        'fast_model': 'model',
        'heavy_model': 'model',
        'project_root': '.'
    }
    v = ConfigValidator(config)
    result = v.validate()
    assert 'Invalid ollama_url format' in result['errors']