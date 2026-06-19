import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");
let source=fs.readFileSync(path.join(root,"js","reliability_panel.js"),"utf8").replace('import { app } from "../../scripts/app.js";','const app = globalThis.__app;');
class E{constructor(tag="div"){this.tagName=tag;this.children=[];this.className="";this.innerHTML="";}append(...x){this.children.push(...x)}replaceChildren(...x){this.children=[...x]}addEventListener(name,fn){this[`on${name}`]=fn}}
let extension,sidebar;const nodes=[];
globalThis.window=globalThis;globalThis.document={createElement:(tag)=>new E(tag)};globalThis.LiteGraph={createNode:(type)=>({type,pos:[0,0]})};
globalThis.__app={graph:{add:(node)=>nodes.push(node)},canvas:{graph_mouse:[10,20],setDirty(){}},extensionManager:{setting:{get:()=>true},registerSidebarTab:(config)=>{sidebar=config}},registerExtension:(config)=>{extension=config}};
vm.runInThisContext(source,{filename:"reliability_panel.js"});
if(!extension||extension.commands.length!==6)throw new Error("reliability extension registration failed");
await extension.setup();if(!sidebar)throw new Error("reliability sidebar was not registered");
const host=new E("aside");sidebar.render(host);if(!host.children.length)throw new Error("reliability sidebar rendered no content");
extension.commands[0].function();if(nodes.length!==1||nodes[0].type!=="CDVerifyPackage")throw new Error("reliability command failed to add node");
console.log("reliability frontend smoke passed");
