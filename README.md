# python-k8s-controller
A python tool that allows you to manage deployments and services in you kubernetes cluster.

# Installation

## Set up Kubernetes
You need to configure you kubernetes RBAC to run this script.
Examples are given below. Make sure to change names and 
namespaces to suit your needs:

File: ``cluster-role.yaml``
```
kind: ClusterRole
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  name: python-k8s-controller
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["list", "watch"]
- apiGroups: ["extensions"]
  resources: ["deployments"]
  verbs: ["list", "watch", "patch", "create", "delete"]
- apiGroups: [""]
  resources: ["services"]
  verbs: ["list", "patch"]
```

File: ``cluster-role-binding.yaml``
```
kind: ClusterRoleBinding
apiVersion: rbac.authorization.k8s.io/v1
metadata:
  name: python-k8s-controller
subjects:
- kind: ServiceAccount
  name: default
  namespace: <your namespace, for production don't use 'default', set up a custom namespace>
roleRef:
  kind: ClusterRole
  name: python-k8s-controller
  apiGroup: rbac.authorization.k8s.io
```

Configure your cluster with the above role and binding
by saving the configuration to a yaml file, adapt the 
``namespace`` of the binding to your needs and then run:
```bash
kubectl apply -f cluster-role.yaml
kubectl apply -f cluster-role-binding.yaml
```

## Run using docker
If you want to run this application interactively using docker:

```bash
# display help
docker run --rm -i -t eduardrosert/python-k8s-controller python controller.py --help
```

```bash
# open interactive shell
docker run --rm -i -t eduardrosert/python-k8s-controller sh
```

## Run using kubernetes
If you want to run this application interactively in your kubernetes cluster/ or your minikube installation:

```bash
# display help
kubectl run -i --tty python-k8s-controller --image=eduardrosert/python-k8s-controller --restart=Never -- python controller.py --help
```

```bash
# open interactive shell
kubectl run -i --tty python-k8s-controller --image=eduardrosert/python-k8s-controller --restart=Never -- sh 
```

# Usage
```
usage: controller.py [-h] [--namespace NAMESPACE] [--deployment-name NAME]
                     [--trigger-rollout] [--duplicate]
                     [--label-selector LABEL_NAME=LABEL_VALUE]
                     [--trigger-smart-rollout] [--no-cleanup] [-v]

A tool to perform certain reoccuring tasks in your kubernetes cluster.

optional arguments:
  -h, --help            show this help message and exit
  --namespace NAMESPACE
                        the kubernetes namespace to work with (default:
                        'default')
  -v, --verbose         increase output verbosity

Deployments:
  Restart or duplicate deployments by name.

  --deployment-name NAME
                        the metadata.name of the deployment
  --trigger-rollout     Triggers a fresh rollout of all Pods by updating the
                        creationTimestamp of the Deployment's Pod template
  --duplicate           Duplicates the deployment. Creates a copy of the
                        deployment under a new name. The current timestamp
                        will be added to the deployment's name to create a
                        unique name, for example 'my-
                        deployment-20191011171423'. If the deployment already
                        has such a suffix, the deployment's copy will get an
                        updated timestamp.

Services:
  Rollout deployments and update associated services by label.

  --label-selector LABEL_NAME=LABEL_VALUE
                        the common label for deployment, pods, and service
                        selector, e.g. app=myapp
  --trigger-smart-rollout
                        Triggers a smart rollout with zero downtime to the
                        service: Duplicates the Deployment(s) with new name(s)
                        and a new 'patch' label, points the service(s) to the
                        new deployment as soon as all pods of the new
                        deployment are running
  --no-cleanup          Deletes the old deployments after patching the
                        service. Use in combination with --trigger-smart-
                        rollout.

Example usage:
----------------------------------------------------------------------------
  Redeploy all pods associated with 'my-deployment' using using the 
  deployment's strategy (e.g. RollingUpdate):

        python controller.py --namespace my-namespace \
                             --deployment-name my-deployment \
                             --trigger-rollout

----------------------------------------------------------------------------
  Create a copy of 'my-deployment':

        python controller.py --namespace my-namespace \
                             --deployment-name my-deployment \
                             --duplicate

  or

        python controller.py --namespace my-namespace \
                             --deployment-name my-deployment-20191011171423 \
                             --duplicate

----------------------------------------------------------------------------
  Trigger a fresh rollout of all deployments with label app=my-app and
  patch the services, then remove the old deployments:

        python controller.py --namespace my-namespace \
                             --label-selector app=my-app \
                             --trigger-smart-rollout

----------------------------------------------------------------------------
  Trigger a fresh rollout of all deployments with label app=my-app and
  patch the services, but leave old deployments in place:

        python controller.py --namespace my-namespace \
                             --label-selector app=my-app \
                             --trigger-smart-rollout
                             --no-cleanup
```

