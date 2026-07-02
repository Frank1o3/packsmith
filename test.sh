#!/bin/bash

rm -r "Frank Pack"

packsmith init "Frank Pack" 26.2 fabric 0.19.3
cd "Frank Pack"

# client mods & some are server side compatible
packsmith add "sodium" mod
packsmith add "iris" mod
packsmith add "sodium extra" mod
packsmith add "entity culling" mod
packsmith add "ferritecore" mod
packsmith add "Mod Menu" mod
packsmith add "Lithium" mod
packsmith add "ImmediatelyFast" mod
packsmith add "More Culling" mod
packsmith add "BadOptimizations" mod
packsmith add "Debugify" mod
packsmith add "Cubes without borders" mod
packsmith add "Remove Reloading Screen" mod
packsmith add "First-person model" mod
packsmith add "Resourcify" mod
packsmith add "Scalablelux" mod
packsmith add "Ksyxis" mod
packsmith add "Skeleton AI Fix" mod
packsmith add "LazyAI" mod
packsmith add "Modernfix-mvus" mod
packsmith add "fusion (connected textures)" mod
packsmith add "Zoomify" mod
packsmith add "LambDynamicLights" mod
packsmith add "Voice-Chat-Interaction" mod
packsmith add "Sound-Physics Remastered" mod
packsmith add "Xaero's-Minimap" mod
packsmith add "Xaero's World Map" mod
packsmith add "Female-Gender" mod
packsmith add "Concurrent Chunk Management Engine (Fabric)" mod
packsmith add "C2ME OpenCL Acceleration Module" mod
packsmith add "Let Me Despawn" mod
packsmith add "NoisiumForked" mod
packsmith add "ServerCore" mod
packsmith add "Leaves Be Gone" mod
packsmith add "Entity Texture Features" mod
packsmith add "Entity Model Features" mod

packsmith add "Fusion Block Transitions" resourcepack
packsmith add "Fusion Connected Blocks" resourcepack
packsmith add "Fusion Connected Glass" resourcepack
packsmith add "Fusion Emissive Ores" resourcepack
packsmith add "Translations for Sodium" resourcepack
packsmith add "Fresh Animations" resourcepack
packsmith add "Fresh Animations: Extensions" resourcepack
packsmith add "Fresh Animations: Player Extension" resourcepack

packsmith add "MakeUp - Ultra Fast" shader
packsmith add "E - LITE Shaders (MakeUp edit)" shader

packsmith resolve
echo ""

packsmith download
echo ""

packsmith export --server
packsmith export --server --client
cd ..
