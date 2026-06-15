# K8s 部署参考模板

[`deployment.yaml`](./deployment.yaml) 是基于本模板生成的服务的**完整 K8s 资源清单**：Namespace / ConfigMap / Secret / Service / Deployment / HPA / PodDisruptionBudget 一份齐。

## 用法

```bash
SERVICE_NAME=payment IMAGE=registry.internal/payment:sha-abc1234 REPLICAS=3 \
  envsubst < examples/k8s/deployment.yaml | kubectl apply -f -
```

或接入 kustomize / helm / argocd 自管。

## 设计点

- **三探针分工**：`/healthz` 进程存活、`/readyz` 真 SELECT 1 + Redis ping、`/startupz` lifespan gate。每个职责单一，K8s 行为可预测（见 ADR §6）
- **单 worker per pod**：扩容靠 pod 数 + HPA，不靠 `uvicorn --workers N`（见 [`../../docs/operations/DEPLOYMENT.md`](../../docs/operations/DEPLOYMENT.md)）
- **`APP_STARTUP_EAGER_CONNECT=true`**：生产强制 eager-probe DB+Redis，连不上 pod 不 ready（见 [`../../docs/architecture/REQUEST_LIFECYCLE.md`](../../docs/architecture/REQUEST_LIFECYCLE.md)）
- **preStop sleep 10s + terminationGracePeriodSeconds 60**：load balancer 排空再 SIGTERM；uvicorn drain in-flight
- **read-only rootfs + non-root uid 10001 + drop all caps + seccomp RuntimeDefault**：CIS K8s benchmark baseline
- **HPA + PDB**：扩缩容上限 20 pod，自愿中断（drain / 升级）至少留 1

## 不在范围

- Ingress / Gateway / ServiceMesh：业务团队自管
- Prometheus ServiceMonitor / Datadog Agent annotation：见各团队 observability ADR
- 数据库 / Redis 自身的 K8s 资源：用 managed service（RDS / ElastiCache）
- NetworkPolicy：按集群基线统一下发
