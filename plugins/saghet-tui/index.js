import { define } from "@opencode/plugin/tui";

const DASHBOARD_URL = "http://127.0.0.1:4780";

export default define({
  id: "saghet-tui",
  setup(context) {
    const showStatus = () => {
      const agents = context.data.location.agent.list() ?? [];
      const mcps = context.data.location.mcp.server.list() ?? [];
      const sessions = context.data.session.list();
      const running = sessions.filter((s) => context.data.session.status(s.id) === "running").length;

      context.ui.toast.show({
        title: `OpenCode-Saghet (${context.themeMode})`,
        message: `Agentes: ${agents.length} | MCP: ${mcps.length} | Sesiones activas: ${running}/${sessions.length}`,
        variant: "info",
        duration: 4500,
      });
    };

    context.keymap.layer(() => ({
      priority: 10,
      commands: [
        {
          id: "saghet.status",
          title: "Saghet: Estado del entorno",
          description: "Muestra resumen de agentes, MCP y sesiones activas",
          group: "OpenCode-Saghet",
          onSelect: showStatus,
        },
        {
          id: "saghet.dashboard",
          title: "Saghet: Abrir Control Center",
          description: `Muestra la URL del Control Center (${DASHBOARD_URL})`,
          group: "OpenCode-Saghet",
          onSelect: () => {
            context.ui.toast.show({
              title: "Saghet Control Center",
              message: `Disponible en ${DASHBOARD_URL}`,
              variant: "success",
              duration: 5000,
            });
          },
        },
      ],
    }));

    const unlisten = context.data.on("session.error", (event) => {
      context.ui.toast.show({
        title: "Saghet: Error en sesión",
        message: String(event?.properties?.error ?? "Error de ejecución detectado"),
        variant: "error",
        duration: 6000,
      });
    });

    return () => {
      unlisten();
    };
  },
});
