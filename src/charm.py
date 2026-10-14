#!/usr/bin/env python3
"""Ollama machine charm: snap install, pull model, publish url+model over `ollama`."""

import os
import subprocess

import ops


class OllamaCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.config_changed, self._reconcile)
        framework.observe(self.on.upgrade_charm, self._reconcile)
        framework.observe(self.on.leader_elected, self._publish)
        framework.observe(self.on.ollama_relation_joined, self._publish)

    def _on_install(self, _):
        self.unit.status = ops.MaintenanceStatus("installing ollama snap")
        subprocess.run(["snap", "install", "ollama"], check=True)

    def _reconcile(self, event):
        port, model = self.config["port"], self.config["model"]
        # The snap defaults to 127.0.0.1; listen on all interfaces so remote units can reach it.
        # Its configure hook restarts the service.
        subprocess.run(["snap", "set", "ollama", f"host=0.0.0.0:{port}"], check=True)

        self.unit.status = ops.MaintenanceStatus(f"pulling {model}")
        env = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{port}"}
        try:
            # The service needs a moment after restart; let the pull retry briefly.
            subprocess.run(
                ["bash", "-c", 'for i in $(seq 30); do ollama pull "$0" && exit 0; sleep 2; done; exit 1', model],
                env={**env, "PATH": env.get("PATH", "") + ":/snap/bin"},
                check=True,
            )
        except subprocess.CalledProcessError:
            self.unit.status = ops.BlockedStatus(f"failed to pull {model}; check model name")
            return

        self.unit.set_ports(port)
        self._publish(event)
        self.unit.status = ops.ActiveStatus(f"serving {model}")

    def _publish(self, _):
        if not self.unit.is_leader():
            return
        for rel in self.model.relations["ollama"]:
            addr = self.model.get_binding(rel).network.ingress_address
            # ponytail: URL of the leader unit only; put a load balancer in front if scaling beyond 1 unit.
            rel.data[self.app].update(
                {"url": f"http://{addr}:{self.config['port']}", "model": self.config["model"]}
            )


if __name__ == "__main__":
    ops.main(OllamaCharm)
