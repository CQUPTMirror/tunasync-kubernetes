# 简介

   采用 FastAPI 开发的船新 Kubernetes Tunasync 简易控制器

## 特性 / Feature

   - 基于 AsyncIO 
   - 采用 RBAC 管理权限
   - 完全支援 Tunasync 配置文件
   - 支援一键更新前端部署
   - 基于 livenessProbe 的定时镜像大小更新
   - 支持选定同步节点

## 如何使用 / HowTo

   ### 开始
   确保 Kubernetes 以及 metrics-server 可用

   参照 `deploy/controller.yaml` 进行部署
   
   部署后访问 `/init` 初始化管理器 或 参照 `deploy/manager.yaml` 部署管理器，并修改 `config.yaml`

   部署后可访问 `/redoc` 或 `/docs` 查看 API 文档

   ### 前端部署
   参照 `deploy/front.yaml`
