"""Composition root. Services use constructor injection, never a global container."""

import punq

from app.config import DeploymentSettings, Limits, Settings, SSHSettings
from app.entities import NodeFactory
from app.infrastructure.auth import SudoPasswordResolver
from app.infrastructure.backups import LocalBackupFiles, XuiBackupValidator
from app.infrastructure.bootstrap import StorageBootstrap
from app.infrastructure.execution import RemoteAgentBuilder, SSHNodeExecutor
from app.infrastructure.keys import LocalSSHKeyFiles
from app.infrastructure.rendering import NodeArtifacts
from app.infrastructure.repositories import (
    SQLiteBackupRepository,
    SQLiteJobRepository,
    SQLiteNodeRepository,
    SQLiteSSHKeyRepository,
)
from app.infrastructure.template import FileNodeTemplate
from app.ports import (
    ArtifactRenderer,
    BackupFiles,
    BackupRepository,
    BackupValidator,
    JobRepository,
    NodeExecutor,
    NodeRepository,
    NodeTemplate,
    SSHKeyFiles,
    SSHKeyRepository,
)
from app.services import BackupService, ExecuteJob, JobService, NodeService, SSHKeyService
from app.services.discovery_config import DiscoveryConfigService
from framework.database import SQLiteDatabase, SQLiteSnapshots
from framework.entities import EntityFactory, JsonCodec, YamlCodec
from framework.network import CommandRunner, KeyOptions, OpenSSHKeys, SSHClient, SSHOptions
from framework.routing import ExceptionHandlers, RouterFactory
from framework.tasks import TaskScheduler, ThreadTaskScheduler
from framework.utils import EnvironmentSecrets, PrivateFiles


def build_container(settings: Settings, *, overrides: dict | None = None) -> punq.Container:
    container = punq.Container()
    container.register(Settings, instance=settings)
    container.register(Limits, instance=settings.limits)
    container.register(DeploymentSettings, instance=settings.deployment)
    container.register(SSHSettings, instance=settings.ssh)
    container.register(
        KeyOptions,
        instance=KeyOptions(
            directory=settings.data_dir / settings.keys_directory,
            binary=settings.ssh.keygen_binary,
            timeout=settings.ssh.keygen_timeout,
        ),
    )
    container.register(
        SSHOptions,
        instance=SSHOptions(
            binary=settings.ssh.binary,
            connect_timeout=settings.ssh.connect_timeout,
            alive_interval=settings.ssh.alive_interval,
            alive_count=settings.ssh.alive_count,
            python_command=settings.ssh.python_command,
            sudo_python_command=settings.ssh.sudo_python_command,
            sudo_password_command=settings.ssh.sudo_password_command,
        ),
    )
    container.register(
        SQLiteDatabase,
        instance=SQLiteDatabase(
            settings.data_dir / settings.database_name, settings.sqlite_timeout
        ),
    )
    container.register(
        PrivateFiles, instance=PrivateFiles(settings.data_dir / settings.backups_directory)
    )
    container.register(TaskScheduler, instance=ThreadTaskScheduler(settings.worker_count))
    for interface, implementation in (
        (NodeRepository, SQLiteNodeRepository),
        (JobRepository, SQLiteJobRepository),
        (BackupRepository, SQLiteBackupRepository),
        (BackupFiles, LocalBackupFiles),
        (BackupValidator, XuiBackupValidator),
        (ArtifactRenderer, NodeArtifacts),
        (NodeExecutor, SSHNodeExecutor),
        (NodeTemplate, FileNodeTemplate),
        (SSHKeyRepository, SQLiteSSHKeyRepository),
        (SSHKeyFiles, LocalSSHKeyFiles),
    ):
        container.register(interface, implementation, scope=punq.Scope.singleton)
    for implementation in (
        JsonCodec,
        YamlCodec,
        EntityFactory,
        NodeFactory,
        SQLiteSnapshots,
        CommandRunner,
        SSHClient,
        EnvironmentSecrets,
        SudoPasswordResolver,
        OpenSSHKeys,
        SSHKeyService,
        RemoteAgentBuilder,
        BackupService,
        ExecuteJob,
        JobService,
        NodeService,
        DiscoveryConfigService,
        StorageBootstrap,
        RouterFactory,
        ExceptionHandlers,
    ):
        container.register(implementation, scope=punq.Scope.singleton)
    for interface, instance in (overrides or {}).items():
        container.register(interface, instance=instance)
    return container
