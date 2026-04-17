#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EC2, RDS, ElastiCache, ECS, EKS 접속 자동화 스크립트 v5.5.0 (macOS 전용)

이 파일은 ec2menu 패키지의 씬 래퍼입니다.
실제 구현은 ec2menu/ 패키지에 있습니다.

실행 방법:
  python3 ec2menu_v5.5.0_mac.py
  python3 -m ec2menu
"""
from ec2menu.main import main

if __name__ == '__main__':
    main()
