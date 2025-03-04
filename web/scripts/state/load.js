const loadPartial = () => {
    const scaleTo = mainSketch.sketchLayer.view.viewSize.width;
    const idx = Math.floor(Math.random() * partialSketches.length);
    const partial = partialSketches[idx][0];
    const drawPrompt = partialSketches[idx][1];
    document.getElementById("partial-message").innerHTML = drawPrompt;
    let loadedPartial = mainSketch.sketchLayer.importSVG(partial);

    loadedPartial.getItems().forEach((item) => {
        if (item instanceof Path) {
            let newElem = mainSketch.sketchLayer.addChild(item.clone());
            newElem.data.fixed = true;
            newElem.strokeCap = "round";
            newElem.strokeJoin = "round";
        }
    });
    loadedPartial.remove();
    scaleGroup(mainSketch.sketchLayer, scaleTo);
    mainSketch.svg = paper.project.exportSVG({
        asString: true,
    });
};

const incrementHistory = () => {
    sketchHistory.historyHolder.push({
        svg: mainSketch.svg,
        loss: mainSketch.semanticLoss,
    });
    timeKeeper.setAttribute("max", String(sketchHistory.historyHolder.length));
    timeKeeper.value = String(sketchHistory.historyHolder.length);
};