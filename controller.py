#!/usr/bin/env python
"""
controller.py

Helps managing deployments and associated services in your kubernetes cluster.

Author:
    Eduard Rosert
Version history:
    0.1, 2019-10-08, initial version

---
MIT License

python-k8s-controller

Copyright (c) 2019 Eduard Rosert

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
---

Requires python kubernetes api: pip install kubernetes

You need to configure you kubernetes RBAC to run this script.
Examples are given below. Make sure to change names and 
namespaces to suit your needs:

--- File: cluster-role.yaml ---
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

--- File: cluster-role-binding.yaml --
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

Configure your cluster with the above role and binding
by saving the configuration to a yaml file and then run:
kubectl apply -f cluster-role.yaml
kubectl apply -f cluster-role-binding.yaml

"""

import sys
import argparse
import datetime
import re
import copy
from os import path, getuid
from pwd import getpwuid
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException
from pprint import pprint
import logging as log


# custom errors

class K8sControllerError(Exception):
   """Base class for other K8sController exceptions"""
   pass

class K8sDeploymentNotFoundError(K8sControllerError):
   """Raised when a deployment was not found"""
   pass

class K8sServiceNotFoundError(K8sControllerError):
   """Raised when a service was not found"""
   pass

class K8sBasenameNotUniqueError(K8sControllerError):
    """Raised then another entity with the same base name was encountered"""
    pass

def getK8sFormattedTimestamp(dtTimestamp = datetime.datetime.utcnow(), format = "%Y-%m-%dT%H:%M:%SZ"):
    return dtTimestamp.strftime(format)

def getSimpleTimestamp(dtTimestamp = datetime.datetime.utcnow(), format = "%Y%m%d%H%M%S"):
    return dtTimestamp.strftime(format)

def getDeploymentPatchBody( creationTimestamp = datetime.datetime.utcnow() ):
    """ Returns the a deployment patch with an updated spec:template:metadata:creationTimestamp """
    timestampNow = getK8sFormattedTimestamp( creationTimestamp )
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "creationTimestamp": timestampNow
                }
            }
        }
    }
    return body

def load_k8s_config(config_file=None):
    """ loads kubernetes configuration from the given config_file or on a best effort basis"""
    
    if not config_file is None:
        # load configuration from the given config file
        log.debug("Loading Kubernetes configuration from file '%s'\n"%(config_file))
        config.load_kube_config(config_file=config_file)
    elif not path.exists('/.dockerenv'):
        # load configuration from the current user's home directory
        config_file = '/home/%s/.kube/config_liberty' % (getpwuid(getuid()).pw_name)
        log.debug("No configuration file provided. Could not find '/.dockerenv' directory, so assuming this script runs outside of a kubernetes cluster. Trying to load the current user's Kubernetes configuration from file '%s'\n"%(config_file))
        config.load_kube_config(config_file=config_file)
    else:
        # assume this script runs inside a pod in your kubernetes cluster
        log.debug("'/.dockerenv' directory detected. Assuming this script runs in pod on your kubernetes cluster. Loading the 'incluster' Kubernetes configuration.\n")
        config.load_incluster_config()

def restart_namespaced_deployment(name, namespace="default", extv1Client=None):
    """ Forces a restart of all pods of a deployment by updating the creationTimestamp """
    if extv1Client is None:
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        extv1Client=client.ExtensionsV1beta1Api()

    # this is a trick to force a redeployment of all pods
    # simply by changing the pod's creation timestamp
    body = getDeploymentPatchBody()
    log.debug("Patch body: \n%s\n"%body)

    try:
        get_namespaced_deployment(name=name, namespace=namespace, extv1Client=extv1Client)
    except K8sDeploymentNotFoundError as e:
        log.error("Error restating deployment: %s\n" %e )
        raise e

    # patch the deployment
    patch_namespaced_deployment(name=name, namespace=namespace, body=body, extv1Client=extv1Client)

def patch_namespaced_deployment(name, namespace="default", body = {}, extv1Client=None):
    """ Patch the given deployment """
    if extv1Client is None:
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        extv1Client=client.ExtensionsV1beta1Api()

    log.debug("Patching deployment '%s' in namespace '%s'"%(name, namespace))
    log.debug("Patch body: \n{0}\n".format(body))
    deployment = extv1Client.patch_namespaced_deployment(name=name, namespace=namespace, body=body)
    log.debug("Patched deployment:\n{0}\n".format(deployment))

def get_namespaced_deployment(name, namespace="default", extv1Client=None):
    """ Gets the configuration of the deployment with a given name 
    
    Raises
    ------
    - ApiException: if the kubernetes client throws an error
    - K8sDeploymentNotFoundError: if a deployment with this name cannot be found
    """
    if extv1Client is None:
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        extv1Client=client.ExtensionsV1beta1Api()

    deploymentList = None
    try:
        deploymentList = extv1Client.list_namespaced_deployment(namespace=namespace, field_selector="metadata.name=%s"%(name))
        log.debug("Deployments found: \n{0}\n".format(deploymentList))
    except ApiException as e:
        log.error("Exception when calling ExtensionsV1beta1Api->list_namespaced_deployment: %s\n" % e)
        raise e

    if (len(deploymentList.items) < 1):
        raise K8sDeploymentNotFoundError("Could not find deployment '%s' in namespace '%s'"%(name, namespace))
    else:
        # metadata.name has to be unique in the namespace, so there can only be one
        return deploymentList.items[0]

def get_namespaced_deployments(label_selector, namespace="default", extv1Client=None):
    """ Returns a list of deployments matching the label_selector (e.g. label_name=label_value) """
    if extv1Client is None:
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        extv1Client=client.ExtensionsV1beta1Api()

    deploymentList = None
    try:
        deploymentList = extv1Client.list_namespaced_deployment(namespace=namespace, label_selector="%s"%(label_selector))
        log.debug("Deployments found: \n{0}\n".format(deploymentList))
    except ApiException as e:
        log.error("Exception when calling ExtensionsV1beta1Api->list_namespaced_deployment: %s\n" % e)
        raise e

    if (len(deploymentList.items) < 1):
        raise K8sDeploymentNotFoundError("Could not find deployments with label '%s' in namespace '%s'"%(label_selector, namespace))
    else:
        # metadata.name has to be unique in the namespace, so there can only be one
        return deploymentList.items

def create_namespaced_deployment(body, namespace="default", extv1Client=None):
    """ Creates a deployment with the given body in the given namespace """
    if extv1Client is None:
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        extv1Client=client.ExtensionsV1beta1Api()

    deployment = None
    try:
        deployment = extv1Client.create_namespaced_deployment(namespace=namespace, body=body)
        log.debug("Deployment created: \n{0}\n".format(deployment))
    except ApiException as e:
        log.error("Exception when calling ExtensionsV1beta1Api->create_namespaced_deployment: %s\n" % e)
        raise e

    return deployment

def getDeploymentBaseName(name):
    """ Strips the timestamp suffix (including the dash) from the name and returns the base name
    
    Example:
    
    getDeploymentBaseName("deployment-basename-20191011134834")

    returns "deployment-basename"
    """
    return re.sub(r'-\d+$', '', name)

def duplicate_deployment_config(body, simpleTimestamp):
    """ Creates a copy of the deployment with a new name and the given label """
    newBody = copy.deepcopy(body)
    newName = getDeploymentBaseName(name=body.metadata.name) #strip the version string at the end of the name
    newBody.metadata.name = "%s-%s" % (newName, simpleTimestamp)
    newBody.metadata.labels["patch"] = simpleTimestamp
    newBody.spec.template.metadata.labels["patch"] = simpleTimestamp
    newBody.metadata.resource_version = ""
    return newBody

def get_namespaced_service(name, namespace="default", v1Client = None):
    """ Gets the configuration of the deployment with a given name """
    if v1Client is None:
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        v1Client = client.CoreV1Api()

    serviceList = None
    try: 
        serviceList = v1Client.list_namespaced_service(namespace=namespace, field_selector="metadata.name=%s"%(name))
        log.debug(serviceList)
    except ApiException as e:
        log.error("Exception when calling CoreV1Api->list_namespaced_deployment: %s\n" % e)
        raise e

    if (len(serviceList.items) < 1):
        raise K8sServiceNotFoundError("Could not find service '%s' in namespace '%s'"%(name, namespace))
    else:
        # metadata.name has to be unique in the namespace, so there can only be one
        return serviceList.items[0]

def get_namespaced_services(label_selector, namespace="default", v1Client = None):
    """ Returns a list of services matching the label_selector (e.g. label_name=label_value) """
    if v1Client is None:
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        v1Client = client.CoreV1Api()

    serviceList = None
    try:
        serviceList = v1Client.list_namespaced_service(namespace=namespace, label_selector="%s"%(label_selector))
        log.debug(serviceList)
    except ApiException as e:
        log.error("Exception when calling CoreV1Api->list_namespaced_deployment: %s\n" % e)
        raise e

    if (len(serviceList.items) < 1):
        raise K8sServiceNotFoundError("Could not find services with label '%s' in namespace '%s'"%(label_selector, namespace))
    else:
        # metadata.name has to be unique in the namespace, so there can only be one
        return serviceList.items

def patch_namespaced_service(name, simpleTimestamp, namespace="default", v1Client = None):
    if v1Client is None:
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        v1Client = client.CoreV1Api()
    
    serviceBody = None
    try:
        serviceBody = get_namespaced_service(name=name, namespace=namespace, v1Client=v1Client)
    except K8sServiceNotFoundError as e:
        log.error("Exception when calling controller->get_namespaced_service: %s\n" % e)
        raise e
        
    # patch the service
    serviceBody.spec.selector["patch"] = simpleTimestamp
    service = v1Client.patch_namespaced_service(name=name, namespace=namespace, body=serviceBody)
    log.debug(service)
    return service

def watch_namespaced_deployment(name, namespace="default", extv1Client=None):
    """ Watches the deployment until all replicas of the deployment are ready """
    if extv1Client is None:
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        extv1Client=client.ExtensionsV1beta1Api()

    stream = watch.Watch().stream( extv1Client.list_namespaced_deployment, namespace)
    for event in stream:
        deployment = event['object']
        if deployment.metadata.name == name:
            # this is the deployment you're looking for
            log.info("Event: %s %s, replicas ready: %s/%s" 
                    % (event['type'], deployment.metadata.name, deployment.status.ready_replicas,deployment.status.replicas ))
            if deployment.status.ready_replicas is not None \
               and deployment.status.replicas is not None \
               and deployment.status.ready_replicas >= deployment.status.replicas:
                log.info("Deployment '%s' ready. Replicas %s/%s!"
                    %(deployment.metadata.name, deployment.status.ready_replicas, deployment.status.replicas))
                log.debug(deployment)
                return deployment

def duplicate_deployment(name, namespace="default", extv1Client=None):
    """ Creates a copy of the deployment under a new name """
    if extv1Client is None :
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        extv1Client=client.ExtensionsV1beta1Api()

    log.debug("looking for deployment '%s' in namespace '%s'..."%(name, namespace))
    dep = None
    try:
        dep = get_namespaced_deployment(name = name, namespace = namespace, extv1Client=extv1Client)
    except K8sDeploymentNotFoundError as e:
        log.error("Deployment '%s' not found in namespace '%s'..."%(name, namespace))
        raise e
    log.debug("Deployment '%s' found."%(dep.metadata.name))
    timestamp = getSimpleTimestamp()
    dep_copy = duplicate_deployment_config(dep, timestamp)
    log.debug("Creating a copy of '%s' with new name '%s' in namespace '%s'"
                %(dep.metadata.name, dep_copy.metadata.name, namespace))
    deployment = create_namespaced_deployment(body=dep_copy, namespace=namespace, extv1Client=extv1Client)
    log.debug("Copy of deployment '%s' created: %s" 
                %(dep.metadata.name, deployment.metadata.name))
    return deployment

def duplicate_deployments(label_selector, namespace="default", extv1Client=None):
    if extv1Client is None :
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        extv1Client=client.ExtensionsV1beta1Api()
    
    
def check_deployments(deployments):
    """ Checks the deployment configurations for duplication. 
    
    Raises 
    ------
    - K8sBasenameNotUniqueError: if basenames of deployments not unique
    """
    # check if configuration is correct
    basenames = {}
    for dep in deployments:
        basename = getDeploymentBaseName(dep.metadata.name)
        log.debug("  Deployment found: %s, basename: %s"%(dep.metadata.name, basename))
        if basename in basenames.keys():
            raise K8sBasenameNotUniqueError("Cannot duplicate Deployment '%s'. Reason: Basename '%s' is not unique. Deployment '%s' with the same base name already exists." 
                                %(dep.metadata.name, basename, basenames[basename]))
        else:
            basenames[basename] = dep.metadata.name

def trigger_smart_rollout(label_selector, namespace="default", v1Client=None, extv1Client=None, cleanup=True):
    """ TODO description """
    if v1Client is None :
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        v1Client = client.CoreV1Api()

    if extv1Client is None :
        # load the kubernetes config
        load_k8s_config()
        #create the api client
        extv1Client=client.ExtensionsV1beta1Api()

    # get the current timestamp
    simpleTimestamp = getSimpleTimestamp()

    log.info("looking for deployments for label selector '%s'..."% label_selector)
    deps = get_namespaced_deployments(label_selector = label_selector,namespace = namespace, extv1Client=extv1Client)
    try:
        check_deployments(deployments=deps)
    except K8sBasenameNotUniqueError as e:
        log.error("Error checking deployments: %s" % e)
        raise e

    for dep in deps:
        dep_copy = duplicate_deployment_config(dep, simpleTimestamp)
        log.info("  Creating duplicate for deployment '%s': %s"%(dep.metadata.name, dep_copy.metadata.name))
        create_namespaced_deployment(body=dep_copy, namespace=namespace, extv1Client=extv1Client)
        #wait for it to finish
        log.info("  Waiting to finish: %s"%(dep_copy.metadata.name))
        watch_namespaced_deployment(name=dep_copy.metadata.name, namespace=namespace, extv1Client=extv1Client)
        log.info("  Done")
    
    #patch the services
    log.info("looking for services...")
    services = get_namespaced_services(label_selector=label_selector, namespace=namespace, v1Client=v1Client)
    for svc in services:
        log.info("  Service found: %s"%(svc.metadata.name))
        log.info("  Patching service: %s"%(svc.metadata.name))
        patch_namespaced_service(svc.metadata.name, simpleTimestamp=simpleTimestamp, namespace=namespace, v1Client=v1Client)
        log.info("  Done")

    if cleanup:
        log.info("deleting old deployments...")
        #delete old deployments
        for dep in deps:
            log.info("  Deleting deployment: %s"%(dep.metadata.name))
            extv1Client.delete_namespaced_deployment(name=dep.metadata.name, namespace=namespace)
            log.info("  Done")
    log.info("All Done.")

parser = argparse.ArgumentParser(
    description='A tool to perform certain reoccuring tasks in your kubernetes cluster.',
    add_help=True,
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog='''
Example usage:
----------------------------------------------------------------------------
  Redeploy all pods associated with 'my-deployment' using using the 
  deployment's strategy (e.g. RollingUpdate):

        python controller.py --namespace my-namespace \\
                             --deployment-name my-deployment \\
                             --trigger-rollout

----------------------------------------------------------------------------
  Create a copy of 'my-deployment':

        python controller.py --namespace my-namespace \\
                             --deployment-name my-deployment \\
                             --duplicate

  or

        python controller.py --namespace my-namespace \\
                             --deployment-name my-deployment-20191011171423 \\
                             --duplicate

----------------------------------------------------------------------------
  Trigger a fresh rollout of all deployments with label app=my-app and
  patch the services, then remove the old deployments:

        python controller.py --namespace my-namespace \\
                             --label-selector app=my-app \\
                             --trigger-smart-rollout

----------------------------------------------------------------------------
  Trigger a fresh rollout of all deployments with label app=my-app and
  patch the services, but leave old deployments in place:

        python controller.py --namespace my-namespace \\
                             --label-selector app=my-app \\
                             --trigger-smart-rollout
                             --no-cleanup

''')

parser.add_argument('--namespace',
                    dest='namespace',
                    metavar='NAMESPACE',
                    default="default",
                    type=str,
                    help='the kubernetes namespace to work with (default: \'default\')')

group1 = parser.add_argument_group('Deployments', 'Restart or duplicate deployments by name.')

group1.add_argument('--deployment-name',
                    dest='deploymentName',
                    metavar='NAME',
                    type=str,
                    help='the metadata.name of the deployment')

group1.add_argument('--trigger-rollout',
                    dest='triggerRollout',
                    action='store_true',
                    help='Triggers a fresh rollout of all Pods by updating the creationTimestamp of the Deployment\'s Pod template')

group1.add_argument('--duplicate',
                    dest='duplicate',
                    action='store_true',
                    help='''
                        Duplicates the deployment.
                        Creates a copy of the deployment under a new name. 
                        The current timestamp will be added to the deployment's name to create a unique name, 
                        for example 'my-deployment-20191011171423'. If the deployment already has such a suffix,
                        the deployment's copy will get an updated timestamp.''')

group2 = parser.add_argument_group('Services', 'Rollout deployments and update associated services by label.')

group2.add_argument('--label-selector',
                    metavar="LABEL_NAME=LABEL_VALUE",
                    dest='labelSelector',
                    type=str,
                    help='the common label for deployment, pods, and service selector, e.g. app=myapp')

group2.add_argument('--trigger-smart-rollout',
                    dest='triggerSmartRollout',
                    action='store_true',
                    help='Triggers a smart rollout with zero downtime to the service: Duplicates the Deployment(s) with new name(s) and a new \'patch\' label, points the service(s) to the new deployment as soon as all pods of the new deployment are running')

group2.add_argument('--no-cleanup',
                    dest='cleanup',
                    action='store_false',
                    help='Deletes the old deployments after patching the service. Use in combination with --trigger-smart-rollout.')


parser.add_argument("-v", "--verbose", help="increase output verbosity",
                    action="store_const", dest="loglevel", const=log.INFO)


if __name__ == "__main__":
    logformat = "[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s"

    args = parser.parse_args()
    if args.loglevel:
        log.basicConfig(format=logformat, level=log.DEBUG) # verbose
    else:
        log.basicConfig(format=logformat, level=log.INFO) # default

    #DEBUG
    log.debug("Parsed arguments: {}".format(args))

    if args.deploymentName is not None and args.triggerRollout:
        #trigger a fresh rollout of deployment
        restart_namespaced_deployment(name = args.deploymentName, namespace = args.namespace)
    elif args.deploymentName is not None and args.duplicate:
        dup = duplicate_deployment(name=args.deploymentName, namespace=args.namespace)
        log.info("Copy of deployment '%s' created: %s" 
                %(args.deploymentName, dup.metadata.name))
    elif args.labelSelector is not None and args.triggerSmartRollout:
        trigger_smart_rollout(label_selector=args.labelSelector, namespace=args.namespace, cleanup=args.cleanup)
    else:
        print("Wrong usage. Possibly missing some command line options.\n")
        parser.print_help()
        sys.exit(1)
