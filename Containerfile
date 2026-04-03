ARG UBUNTU_RELEASE=rolling

FROM ubuntu:$UBUNTU_RELEASE

ARG DESKTOP=nogui

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -yq python3 \
                                                       python3-click \
                                                       python3-requests \
                                                       python3-fasteners \
                                                       umoci \
                                                       skopeo \
                                                       jq \
                                                       git \
                                                       sudo \
                                                       pacman-package-manager \
                                                       linux-generic \
                                                       systemd \
                                                       systemd-container \
                                                       locales \
                                                       grub2-common \
                                                       ubuntu-standard \
                                                       dracut \
                                                       software-properties-common

RUN if [ "$DESKTOP" = gnome ]; then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -yq ubuntu-desktop; \
  elif [ "$DESKTOP" = plasma ]; then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -yq kubuntu-desktop; fi

RUN <<EOT
userdel -r ubuntu || :
groupdel ubuntu || :
groupadd -r sudo || :
groupadd -r wheel || :
mkdir -p /etc/sudoers.d
cat > /etc/sudoers.d/00sudo_wheel <<EOF
%sudo     ALL=(ALL) ALL
%wheel    ALL=(ALL) ALL
EOF

add-apt-repository -y universe
add-apt-repository -y multiverse
EOT
