cmake_minimum_required(VERSION 3.20)
project(nimbus-drive-dolphin VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(ECM 6.0 REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
include(KDEInstallDirs)
include(KDECMakeSettings)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core DBus Widgets)
find_package(KF6 6.0 REQUIRED COMPONENTS KIO CoreAddons)

add_definitions(-DQT_NO_CAST_FROM_ASCII -DQT_NO_KEYWORDS)

# Emblems on files: cloud / downloading / downloaded / offline / conflict.
kcoreaddons_add_plugin(nimbusoverlay
    SOURCES overlayplugin.cpp nimbus.cpp
    INSTALL_NAMESPACE "kf6/overlayicon")
target_link_libraries(nimbusoverlay KF6::KIOCore Qt6::DBus)

# Context menu: download / free up space / keep offline.
kcoreaddons_add_plugin(nimbusactions
    SOURCES actionplugin.cpp nimbus.cpp
    INSTALL_NAMESPACE "kf6/kfileitemaction")
target_link_libraries(nimbusactions KF6::KIOWidgets KF6::CoreAddons Qt6::DBus Qt6::Widgets)
