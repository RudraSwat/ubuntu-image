"""Flow for building a ubuntu classic disk image."""

import os
import re
import shutil
import logging

from subprocess import CalledProcessError
from tempfile import gettempdir
from ubuntu_image.common_builder import AbstractImageBuilderState
from ubuntu_image.helpers import (
     check_root_privilege, get_host_arch, live_build, run)
from ubuntu_image.parser import (
     BootLoader, FileSystemType, StructureRole)


DEFAULT_FS = 'ext4'
DEFAULT_FS_LABEL = 'writable'
_logger = logging.getLogger('ubuntu-image')


class ClassicBuilder(AbstractImageBuilderState):
    def __init__(self, args):
        super().__init__(args)
        self.gadget_tree = args.gadget_tree
        # It's required to run ubuntu-image as root to build classic image.
        check_root_privilege()

    def __getstate__(self):
        state = super().__getstate__()
        state.update(
            gadget_tree=self.gadget_tree,
            )
        return state

    def __setstate__(self, state):
        super().__setstate__(state)
        self.gadget_tree = state['gadget_tree']

    def prepare_gadget_tree(self):
        gadget_dir = os.path.join(self.unpackdir, 'gadget')
        shutil.copytree(self.gadget_tree, gadget_dir)
        # We assume the gadget tree was built from a gadget source tree using
        # snapcraft prime so the gadget.yaml file is expected in the meta/
        # directory.
        self.yaml_file_path = os.path.join(
            gadget_dir, 'meta', 'gadget.yaml')
        super().prepare_gadget_tree()

    def prepare_image(self):
        if not self.args.filesystem:
            try:
                # Configure it with environment variables.
                env = {}
                if self.args.project is not None:
                    env['PROJECT'] = self.args.project
                if self.args.suite is not None:
                    env['SUITE'] = self.args.suite
                if self.args.arch is not None:
                    env['ARCH'] = self.args.arch
                if self.args.subproject is not None:
                    env['SUBPROJECT'] = self.args.subproject
                if self.args.subarch is not None:
                    env['SUBARCH'] = self.args.subarch
                if self.args.with_proposed:
                    env['PROPOSED'] = '1'
                if self.args.extra_ppas is not None:
                    env['EXTRA_PPAS'] = ' '.join(self.args.extra_ppas)
                # Only generate a single rootfs tree for classic images.
                env['IMAGEFORMAT'] = 'none'
                # ensure ARCH is set
                if self.args.arch is None:
                    env['ARCH'] = get_host_arch()
                live_build(self.unpackdir, env)
            except CalledProcessError:
                if self.args.debug:
                    _logger.exception('Full debug traceback follows')
                self.exitcode = 1
                # Stop the state machine here by not appending a next step.
                return

        super().prepare_image()

    def _prepare_rootfs_system_boot_mount(self, dst, fstab_contents):
        fstab_additions = ''
        boot_partition = None
        for volume in self.gadget.volumes.values():
            for part in volume.structures:
                if (part.role is StructureRole.system_boot and
                        part.filesystem_label and
                        part.filesystem is not FileSystemType.none):
                    boot_partition = part
                    # We also need the volume, but that's set by the loop
                    # above.
                    break
        if boot_partition:
            # Check if the partition is mounted somewhere already.
            # If it is, we assume that the rootfs build knows better what
            # to do with it and not meddle in fstab etc.
            fs_label = 'LABEL={}'.format(boot_partition.filesystem_label)
            if fs_label not in fstab_contents:
                # Add a fstab entry for the system-boot partition, mounting
                # in a common /boot/system-boot directory.
                system_boot_dir = os.path.join(dst, 'boot', 'system-boot')
                os.makedirs(system_boot_dir, exist_ok=True)
                fstab_additions = \
                    'LABEL={}   /boot/system-boot    {}    ' \
                    'defaults    0 1\n'.format(
                        boot_partition.filesystem_label,
                        boot_partition.filesystem.name)
                # If the volume uses grub, we need /boot/grub pointing to
                # the boot partition.
                if volume.bootloader is BootLoader.grub:
                    grub_dir = os.path.join(dst, 'boot', 'grub')
                    if os.path.exists(grub_dir):
                        if os.path.isdir(grub_dir):
                            shutil.rmtree(grub_dir, ignore_errors=True)
                        else:
                            os.unlink(grub_dir)
                    os.symlink('/boot/system-boot', grub_dir)
                # If the volume uses uboot, we need /boot/firmware pointing
                # to the boot partition
                elif volume.bootloader is BootLoader.uboot:
                    firmware_dir = os.path.join(dst, 'boot', 'firmware')
                    if os.path.exists(firmware_dir):
                        if os.path.isdir(firmware_dir):
                            shutil.rmtree(firmware_dir, ignore_errors=True)
                        else:
                            os.unlink(firmware_dir)
                    os.symlink('/boot/system-boot', firmware_dir)
        return fstab_additions

    def populate_rootfs_contents(self):
        dst = self.rootfs
        if self.args.filesystem:
            src = self.args.filesystem
            # 'cp -a' is faster than the python functions and makes sure all
            # meta information is preserved.
            run('cp -a {} {}'.format(os.path.join(src, '*'), dst), shell=True)
        else:
            src = os.path.join(self.unpackdir, 'chroot')
            for subdir in os.listdir(src):
                shutil.move(os.path.join(src, subdir),
                            os.path.join(dst, subdir))
        # Remove default grub bootloader settings as we ship bootloader bits
        # (binary blobs and grub.cfg) to a generated rootfs locally.
        grub_folder = os.path.join(dst, 'boot', 'grub')
        if os.path.exists(grub_folder):
            for file_name in os.listdir(grub_folder):
                file_path = os.path.join(grub_folder, file_name)
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path, ignore_errors=True)
                else:
                    os.unlink(file_path)
        # Modify the system's fstab to make sure everything is ready for our
        # image to work correctly.
        # TODO We need the EFI partition in fstab too
        fstab_path = os.path.join(dst, 'etc', 'fstab')
        if os.path.exists(fstab_path):
            # Replace pre-defined LABEL in /etc/fstab with the one
            # we're using 'LABEL=writable' in grub.cfg.
            with open(fstab_path, 'r') as fstab:
                new_content = re.sub(r'(LABEL=)\S+',
                                     r'\1{}'.format(DEFAULT_FS_LABEL),
                                     fstab.read(), count=1)
            # Insert LABEL entry if it's not found at fstab
            fs_label = 'LABEL={}'.format(DEFAULT_FS_LABEL)
            if fs_label not in new_content:
                new_content += 'LABEL={}   /   {}   defaults    0 0\n'.format(
                    DEFAULT_FS_LABEL, DEFAULT_FS)
            # While we're at it, find if the schema defines a system-boot
            # partition with a filesystem label.  If it does, we want to
            # mount it in a special directory for future usage.
            new_content += self._prepare_rootfs_system_boot_mount(
                dst, new_content)
            # Write the new fstab into place.
            with open(fstab_path, 'w') as fstab:
                fstab.write(new_content)
        if self.cloud_init is not None:
            # LP: #1633232 - Only write out meta-data when the --cloud-init
            # parameter is given.
            seed_dir = os.path.join(dst, 'var', 'lib', 'cloud', 'seed')
            cloud_dir = os.path.join(seed_dir, 'nocloud-net')
            os.makedirs(cloud_dir, exist_ok=True)
            metadata_file = os.path.join(cloud_dir, 'meta-data')
            with open(metadata_file, 'w', encoding='utf-8') as fp:
                print('instance-id: nocloud-static', file=fp)
            userdata_file = os.path.join(cloud_dir, 'user-data')
            shutil.copy(self.cloud_init, userdata_file)
        super().populate_rootfs_contents()

    def generate_manifests(self):
        # After the images are built, we would also like to have some image
        # manifests exported so that one can easily check what packages have
        # been installed on the rootfs. We utilize dpkg-query tool to generate
        # the manifest file for classic image. Packages like casper which is
        # only useful in a live CD/DVD are removed.
        # The deprecated words can be found below:
        # https://help.ubuntu.com/community/MakeALiveCD/DVD/BootableFlashFromHarddiskInstall
        deprecated_words = ['ubiquity', 'casper']
        manifest_path = os.path.join(self.output_dir, 'filesystem.manifest')
        tmpfile_path = os.path.join(gettempdir(), 'filesystem.manifest')
        with open(tmpfile_path, 'w+') as tmpfile:
            query_cmd = ['sudo', 'chroot', self.rootfs, 'dpkg-query', '-W',
                         '--showformat=${Package} ${Version}\n']
            run(query_cmd, stdout=tmpfile, stderr=None, env=os.environ)
            tmpfile.seek(0, 0)
            with open(manifest_path, 'w') as manifest:
                for line in tmpfile:
                    if not any(word in line for word in deprecated_words):
                        manifest.write(line)
        super().generate_manifests()
