# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

import os
from typing import Dict, Any


def _env_first(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return default

class ServiceConfig:
    """Configuration for service API connections"""
    
    @staticmethod
    def get_api_config() -> Dict[str, Any]:
        """
        Get API configuration from environment variables or default settings

        Returns:
            Dictionary with API configuration
        """
        return {
            'base_url': os.environ.get('API_BASE_URL', 'http://localhost:9380'),
            'api_key': os.environ.get('API_KEY', ''),
            'default_dataset_id': os.environ.get('DEFAULT_DATASET_ID', ''),
            'serper_api_key': os.environ.get('SERPER_API_KEY', ''),
            'milvus_host': os.environ.get('MILVUS_HOST', 'localhost'),
            'milvus_port': int(os.environ.get('MILVUS_PORT', '19530')),
            'policy_collection': os.environ.get('POLICY_COLLECTION', 'policy_documents'),
            # DeepResearch API keys
            'bochaai_api_key': os.environ.get('BOCHA_API_KEY', ''),
            'dashscope_api_key': _env_first('LLM_API_KEY', 'DASHSCOPE_API_KEY', 'OPENAI_API_KEY'),
            'dashscope_base_url': _env_first('LLM_BASE_URL', 'DASHSCOPE_BASE_URL', 'OPENAI_BASE_URL'),
        } 
