#!/usr/bin/env bash
protoc_version=$1

apt-get install autoconf automake libtool curl make g++ unzip
wget https://github.com/protocolbuffers/protobuf/releases/protobuf-cpp-${protoc_version}.zip
unzip protobuf-cpp-${protoc_version}.zip
cd protobuf-cpp-${protoc_version}
./configure
make
make install
ldconfig
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=cpp
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION_VERSION=2
