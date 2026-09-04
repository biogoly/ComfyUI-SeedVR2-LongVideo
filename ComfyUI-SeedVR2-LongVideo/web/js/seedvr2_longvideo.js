import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

app.registerExtension({
    name: "SeedVR2.LongVideo.Upload",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SeedVR2LongVideoInput") {
            return;
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;

        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);

            const videoWidget = this.widgets?.find((w) => w.name === "video");
            if (!videoWidget) {
                return result;
            }

            this.addWidget("button", "choose video to upload", null, async () => {
                const input = document.createElement("input");
                input.type = "file";
                input.accept = "video/*";
                input.style.display = "none";
                document.body.appendChild(input);

                input.onchange = async () => {
                    try {
                        const file = input.files?.[0];
                        if (!file) return;

                        const body = new FormData();
                        body.append("image", file);
                        body.append("type", "input");

                        const response = await api.fetchApi("/upload/image", {
                            method: "POST",
                            body,
                        });

                        if (!response.ok) {
                            throw new Error(`Upload failed: HTTP ${response.status}`);
                        }

                        const data = await response.json();
                        const name = data?.name ?? file.name;
                        const subfolder = data?.subfolder ?? "";
                        const value = subfolder ? `${subfolder}/${name}` : name;

                        // Dynamic COMBO options are populated by the Python node.
                        // Add the freshly uploaded path locally so it can be selected immediately.
                        if (videoWidget.options?.values && !videoWidget.options.values.includes(value)) {
                            videoWidget.options.values.push(value);
                        }

                        videoWidget.value = value;
                        videoWidget.callback?.(value);
                        this.setDirtyCanvas(true, true);
                    } catch (error) {
                        console.error("[SeedVR2 Long Video] upload failed", error);
                        alert(`SeedVR2 Long Video upload failed:\n${error}`);
                    } finally {
                        input.remove();
                    }
                };

                input.click();
            });

            return result;
        };
    },
});
