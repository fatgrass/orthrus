'''
Orthrus commands implementation
'''
import os
import sys
import shutil
import subprocess
import binascii
import ConfigParser
import tarfile
import time
import threading
from Queue import Queue
# import shlex
# import pty
from orthrusutils import orthrusutils as util
from builder import builder as b

class OrthrusCreate(object):

    def __init__(self, args, config):
        self.args = args
        self.config = config

    def create(self, dest, BEnv, logfn):

        install_path = dest
        os.mkdir(install_path)

        ### Configure
        util.color_print_singleline(util.bcolors.HEADER, "\t\t[+] Configure... ")

        config_flags = ['--prefix=' + os.path.abspath(install_path)] + \
                       self.args.configure_flags.split(" ")

        builder = b.Builder(b.BuildEnv(BEnv),
                            config_flags,
                            self.config['orthrus']['directory'] + "/logs/" + logfn)

        if not builder.configure():
            util.color_print(util.bcolors.FAIL, "failed")
            return False

        util.color_print(util.bcolors.OKGREEN, "done")

        ### Make install
        util.color_print_singleline(util.bcolors.OKGREEN, "\t\t[+] Compile and install... ")

        if not builder.make_install():
            util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
            return False

        util.copy_binaries(install_path + "bin/")
        util.color_print(util.bcolors.OKGREEN, "done")
        return True

    def run(self):
        util.color_print(util.bcolors.BOLD + util.bcolors.HEADER, "[+] Create Orthrus workspace")
        
        if not os.path.exists(self.config['orthrus']['directory']):
            os.mkdir(self.config['orthrus']['directory'])
            os.mkdir(self.config['orthrus']['directory'] + "/binaries/")
            os.mkdir(self.config['orthrus']['directory'] + "/conf/")
            os.mkdir(self.config['orthrus']['directory'] + "/logs/")
            os.mkdir(self.config['orthrus']['directory'] + "/jobs/")
            os.mkdir(self.config['orthrus']['directory'] + "/archive/")
        else:
            util.color_print(util.bcolors.ERROR, "Error: Orthrus workspace already exists!")
            return False

        # AFL-ASAN
        if self.args.afl_asan:

            ### Prepare
            util.color_print(util.bcolors.HEADER,
                             "\t[+] Installing binaries for afl-fuzz with AddressSanitizer")
              
            install_path = self.config['orthrus']['directory'] + "/binaries/afl-asan/"
            if not self.create(install_path, b.BuildEnv.BEnv_afl_asan, 'afl-asan_inst.log'):
                return False

            #
            # ASAN Debug 
            #
            util.color_print(util.bcolors.HEADER,
                             "\t[+] Installing binaries for debug with AddressSanitizer")
            install_path = self.config['orthrus']['directory'] + "/binaries/asan-dbg/"
            if not self.create(install_path, b.BuildEnv.BEnv_asan_debug, 'afl-asan_dbg.log'):
                return False

        ### AFL-HARDEN
        if self.args.afl_harden:
            util.color_print(util.bcolors.HEADER,
                             "\t[+] Installing binaries for afl-fuzz in harden mode")
            install_path = self.config['orthrus']['directory'] + "/binaries/afl-harden/"
            if not self.create(install_path, b.BuildEnv.BEnv_afl_harden, 'afl_harden.log'):
                return False

            #
            # Harden Debug 
            #
            util.color_print(util.bcolors.HEADER,
                             "\t[+] Installing binaries for debug in harden mode")
            install_path = self.config['orthrus']['directory'] + "/binaries/harden-dbg/"
            if not self.create(install_path, b.BuildEnv.BEnv_harden_debug, 'afl_harden_dbg.log'):
                return False

        ### Coverage
        if self.args.coverage:
            util.color_print(util.bcolors.HEADER, "\t[+] Installing binaries for obtaining test coverage information")
            install_path = self.config['orthrus']['directory'] + "/binaries/coverage/"
            if not self.create(install_path, b.BuildEnv.BEnv_coverage, 'gcc_coverage.log'):
                return False

        return True

class OrthrusAdd(object):
    
    def __init__(self, args, config):
        self._args = args
        self._config = config
    
    def run(self):
        util.color_print(util.bcolors.BOLD + util.bcolors.HEADER + "[+] Adding fuzzing job to Orthrus workspace" + util.bcolors.ENDC + "\n")
        
        util.color_print("\t\t[+] Check Orthrus workspace... ")
        sys.stdout.flush() 
        if not os.path.exists(self._config['orthrus']['directory'] + "/binaries/"):
            util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
        util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
        
        if self._args.job:
            jobId = str(binascii.crc32(self._args.job) & 0xffffffff)
            jobTarget = self._args.job.split(" ")[0]
            jobParams = " ".join(self._args.job.split(" ")[1:])
            util.color_print("\t\t[+] Adding job for [" + jobTarget + "]... ")
            sys.stdout.flush()
            
            if os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId):
                util.color_print(util.bcolors.FAIL + "already exists!" + util.bcolors.ENDC + "\n")
                return False
            os.mkdir(self._config['orthrus']['directory'] + "/jobs/" + jobId)
            os.mkdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-in")
            os.mkdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out")
            
            job_config = ConfigParser.ConfigParser()
            job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
            job_config.add_section(jobId)
            job_config.set(jobId, "target", jobTarget)
            job_config.set(jobId, "params", jobParams)
            with open(self._config['orthrus']['directory'] + "/jobs/jobs.conf", 'wb') as job_file:
                job_config.write(job_file)
            util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            
            util.color_print("\t\t[+] Configuring job for [" + jobTarget + "]... ")
            sys.stdout.flush()
            
            asanjob_config = ConfigParser.ConfigParser()
            asanjob_config.add_section("afl.dirs")
            asanjob_config.set("afl.dirs", "input", ".orthrus/jobs/" + jobId + "/afl-in")
            asanjob_config.set("afl.dirs", "output", ".orthrus/jobs/" + jobId + "/afl-out")
            asanjob_config.add_section("target")
            asanjob_config.set("target", "target", ".orthrus/binaries/afl-asan/bin/" + jobTarget)
            asanjob_config.set("target", "cmdline", jobParams)
            asanjob_config.add_section("afl.ctrl")
            asanjob_config.set("afl.ctrl", "file", ".orthrus/jobs/" + jobId + "/afl-out/.cur_input_asan")
            asanjob_config.set("afl.ctrl", "timeout", "3000+")
            asanjob_config.set("afl.ctrl", "mem_limit", "800")
            asanjob_config.add_section("job")
            asanjob_config.set("job", "session", "SESSION")
            if os.path.exists(self._config['orthrus']['directory'] + "binaries/afl-harden"):
                asanjob_config.set("job", "slave_only", "on")
            with open(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/asan-job.conf", 'wb') as job_file:
                asanjob_config.write(job_file)
                
            hardenjob_config = ConfigParser.ConfigParser()
            hardenjob_config.add_section("afl.dirs")
            hardenjob_config.set("afl.dirs", "input", ".orthrus/jobs/" + jobId + "/afl-in")
            hardenjob_config.set("afl.dirs", "output", ".orthrus/jobs/" + jobId + "/afl-out")
            hardenjob_config.add_section("target")
            hardenjob_config.set("target", "target", ".orthrus/binaries/afl-harden/bin/" + jobTarget)
            hardenjob_config.set("target", "cmdline", jobParams)
            hardenjob_config.add_section("afl.ctrl")
            hardenjob_config.set("afl.ctrl", "file", ".orthrus/jobs/" + jobId + "/afl-out/.cur_input_harden")
            hardenjob_config.set("afl.ctrl", "timeout", "3000+")
            hardenjob_config.set("afl.ctrl", "mem_limit", "800")
            hardenjob_config.add_section("job")
            hardenjob_config.set("job", "session", "SESSION")
            with open(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/harden-job.conf", 'wb') as job_file:
                hardenjob_config.write(job_file)
            util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            
            if self._args.sample:
                util.color_print("\t\t[+] Adding initial samples for job [" + jobTarget + "]... ")
                sys.stdout.flush()
                if os.path.isdir(self._args.sample):
                    for dirpath, dirnames, filenames in os.walk(self._args.sample):
                        for fn in filenames:
                            fpath = os.path.join(dirpath, fn)
                            if os.path.isfile(fpath):
                                shutil.copy(fpath, self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-in/")
                elif os.path.isfile(self._args.sample):
                    shutil.copy(self._args.sample, self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-in/")
                util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
        if self._args.job_id:
            if self._args.sample:
                jobId = self._args.job_id
                util.color_print("\t\t[+] Adding samples for job [" + jobId + "]... ")
                sys.stdout.flush()
                if os.path.isdir(self._args.sample):
                    for dirpath, dirnames, filenames in os.walk(self._args.sample):
                        for fn in filenames:
                            fpath = os.path.join(dirpath, fn)
                            if os.path.isfile(fpath):
                                shutil.copy(fpath, self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-in/")
                elif os.path.isfile(self._args.sample):
                    shutil.copy(self._args.sample, self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-in/")
                util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            
            if self._args._import:
                jobId = self._args.job_id
                next_session = 0
                
                util.color_print("\t\t[+] Import afl sync dir for job [" + jobId + "]... ")
                sys.stdout.flush()
                if not tarfile.is_tarfile(self._args._import):
                    util.color_print(util.bcolors.FAIL + "failed!" + util.bcolors.ENDC + "\n")
                    return False
                if not os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out/"):
                    util.color_print(util.bcolors.FAIL + "failed!" + util.bcolors.ENDC + "\n")
                    return False
                
                syncDir = os.listdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out/")
                for directory in syncDir:
                    if "SESSION" in directory:
                        next_session += 1
                
                is_single = True
                with tarfile.open(self._args._import, "r") as tar:
                    try:
                        info = tar.getmember("fuzzer_stats")
                    except KeyError:
                        is_single = False
                        
                    if is_single:
                        outDir = self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out/SESSION" + "{:03d}".format(next_session)
                        os.mkdir(outDir)
                        tar.extractall(outDir)
                    else:
                        tmpDir = self._config['orthrus']['directory'] + "/jobs/" + jobId + "/tmp/"
                        os.mkdir(tmpDir)
                        tar.extractall(tmpDir)
                        for directory in os.listdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/tmp/"):
                            outDir = self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out/SESSION" + "{:03d}".format(next_session)
                            shutil.move(tmpDir + directory, outDir)
                            next_session += 1
                        shutil.rmtree(tmpDir)
                util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
                
                util.color_print("\t\t[+] Minimizing corpus for job [" + jobId + "]... \n")
                sys.stdout.flush()
                 
                job_config = ConfigParser.ConfigParser()
                job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
                export = {}
                export['PYTHONUNBUFFERED'] = "1"
                env = os.environ.copy()
                env.update(export)
         
                launch = ""
                if os.path.exists(self._config['orthrus']['directory'] + "/binaries/afl-harden"):
                    launch = self._config['orthrus']['directory'] + "/binaries/afl-harden/bin/" + job_config.get(jobId, "target") + " " + job_config.get(jobId, "params").replace("&","\&")
                else:
                    launch = self._config['orthrus']['directory'] + "/binaries/afl-asan/bin/" + job_config.get(jobId, "target") + " " + job_config.get(jobId, "params")
                cmin = " ".join(["afl-minimize", "-c", self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect", "--cmin", "--cmin-mem-limit=800", "--cmin-timeout=5000", "--dry-run", self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out", "--", "'" + launch + "'"])
                p = subprocess.Popen(cmin, bufsize=0, shell=True, executable='/bin/bash', env=env, stdout=subprocess.PIPE)
                for line in p.stdout:
                    if "[*]" in line or "[!]" in line:
                        util.color_print("\t\t\t" + line)
                        
                reseed_cmd = " ".join(["afl-minimize", "-c", self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin", "--reseed", self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out", "--", "'" + launch + "'"])
                p = subprocess.Popen(reseed_cmd, bufsize=0, shell=True, executable='/bin/bash', env=env, stdout=subprocess.PIPE)
                for line in p.stdout:
                    if "[*]" in line or "[!]" in line:
                        util.color_print("\t\t\t" + line)
                        
                if os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect"):
                    shutil.rmtree(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect")
                if os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin"):
                    shutil.rmtree(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin")
                if os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin.crashes"):
                    shutil.rmtree(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin.crashes")
                if os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin.hangs"):
                    shutil.rmtree(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin.hangs")
            
        return True

class OrthrusRemove(object):
    
    def __init__(self, args, config):
        self._args = args
        self._config = config
    
    def run(self):
        util.color_print(util.bcolors.BOLD + util.bcolors.HEADER + "[+] Removing fuzzing job from Orthrus workspace" + util.bcolors.ENDC + "\n")
        
        util.color_print("\t\t[+] Check Orthrus workspace... ")
        sys.stdout.flush() 
        if not os.path.exists(self._config['orthrus']['directory'] + "/binaries/"):
            util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
        util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
        
        if self._args.job_id:
            util.color_print("\t\t[+] Archiving data for job [" + self._args.job_id + "]... ")
            sys.stdout.flush()
            if not os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + self._args.job_id):
                util.color_print(util.bcolors.FAIL + "failed!" + util.bcolors.ENDC + "\n")
                return False
            shutil.move(self._config['orthrus']['directory'] + "/jobs/" + self._args.job_id, self._config['orthrus']['directory'] + "/archive/" + time.strftime("%Y-%m-%d-%H:%M:%S") + "-" + self._args.job_id)
            util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            
            util.color_print("\t\t[+] Removing job for [" + self._args.job_id + "]... ")
            sys.stdout.flush()
            job_config = ConfigParser.ConfigParser()
            job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
            job_config.remove_section(self._args.job_id)
            with open(self._config['orthrus']['directory'] + "/jobs/jobs.conf", 'wb') as job_file:
                job_config.write(job_file)
            util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            
        return True

class OrthrusStart(object):
    
    def __init__(self, args, config):
        self._args = args
        self._config = config
    
    def _get_cpu_core_info(self):
        num_cores = subprocess.check_output("nproc", shell=True, stderr=subprocess.STDOUT)
        
        return int(num_cores)
    
    def _start_fuzzers(self, jobId, available_cores):
        start_cmd = ""
        if os.listdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out/") == []:
            start_cmd = "start"
        else:
            start_cmd = "resume"

        core_per_subjob = available_cores / 2
        if core_per_subjob == 0:
            core_per_subjob = 1

        if os.path.exists(self._config['orthrus']['directory'] + "/binaries/afl-harden"):
            harden_file = open(self._config['orthrus']['directory'] + "/logs/afl-harden.log", "w")
            p = subprocess.Popen(" ".join(["afl-multicore", "--config=.orthrus/jobs/" + jobId + "/harden-job.conf", start_cmd, str(core_per_subjob), "-v"]), shell=True, stdout=harden_file, stderr=subprocess.PIPE)
            p.wait()
            util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            
            output = open(self._config['orthrus']['directory'] + "/logs/afl-harden.log", "r")
            for line in output:
                if "Starting master" in line or "Starting slave" in line:
                    util.color_print("\t\t\t" + line)
                if " Master " in line or " Slave " in line:
                    util.color_print("\t\t\t\t" + util.bcolors.OKGREEN + "[+]" + util.bcolors.ENDC + line)
            output.close()
            
            if os.path.exists(self._config['orthrus']['directory'] + "/binaries/afl-asan"):
                asan_file = open(self._config['orthrus']['directory'] + "/logs/afl-asan.log", "w")
                p = subprocess.Popen("afl-multicore --config=.orthrus/jobs/" + jobId + "/asan-job.conf " + "add" + " " + str(core_per_subjob) +" -v", shell=True, stdout=asan_file, stderr=subprocess.STDOUT)
                p.wait()
                output2 = open(self._config['orthrus']['directory'] + "/logs/afl-asan.log", "r")
                for line in output2:
                    if "Starting master" in line or "Starting slave" in line:
                        util.color_print("\t\t\t" + line)
                    if " Master " in line or " Slave " in line:
                        util.color_print("\t\t\t\t" + util.bcolors.OKGREEN + "[+]" + util.bcolors.ENDC + line)
                output2.close()
        elif os.path.exists(self._config['orthrus']['directory'] + "/binaries/afl-asan"):
            asan_file = open(self._config['orthrus']['directory'] + "/logs/afl-asan.log", "w")
            p = subprocess.Popen("afl-multicore --config=.orthrus/jobs/" + jobId + "/asan-job.conf " + start_cmd + " " + str(available_cores) +" -v", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            p.wait()
            util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            
            output2 = open(self._config['orthrus']['directory'] + "/logs/afl-asan.log", "r")
            for line in output2:
                if "Starting master" in line or "Starting slave" in line:
                    util.color_print("\t\t\t" + line)
                if " Master " in line or " Slave " in line:
                    util.color_print("\t\t\t\t" + util.bcolors.OKGREEN + "[+]" + util.bcolors.ENDC + line)
            output2.close()
                
        return True
    
    def _tidy_sync_dir(self, jobId):
        syncDir = self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out"
        for session in os.listdir(syncDir):
            if os.path.isfile(syncDir + "/" + session):
                os.remove(syncDir + "/" + session)
            if os.path.isdir(syncDir + "/" + session):
                for directory in os.listdir(syncDir + "/" + session):
                    if "crashes." in directory:
                        for num, filename in enumerate(os.listdir(syncDir + "/" + session + "/" + directory)):
                            src_path = syncDir + "/" + session + "/" + directory + "/" + filename
                            dst_path = syncDir + "/" + session + "/" + "crashes" + "/" + filename
                            if not os.path.isfile(dst_path):
                                #dst_path += "," + str(num)
                                shutil.move(src_path, dst_path)
                        shutil.rmtree(syncDir + "/" + session + "/" + directory + "/")
                    if "hangs." in directory:
                        for num, filename in enumerate(os.listdir(syncDir + "/" + session + "/" + directory)):
                            src_path = syncDir + "/" + session + "/" + directory + "/" + filename
                            dst_path = syncDir + "/" + session + "/" + "hangs" + "/" + filename
                            if not os.path.isfile(dst_path):
                                #dst_path += "," + str(num)
                                shutil.move(src_path, dst_path)
                        shutil.rmtree(syncDir + "/" + session + "/" + directory + "/")
    #                 if "queue." in directory:
    #                     for num, filename in enumerate(os.listdir(syncDir + "/" + session + "/" + directory)):
    #                         src_path = syncDir + "/" + session + "/" + directory + "/" + filename
    #                         dst_path = syncDir + "/" + session + "/" + "queue" + "/" + filename
    #                         if os.path.isfile(dst_path):
    #                             dst_path += "," + str(num)
    #                         shutil.move(src_path, dst_path)
    #                     shutil.rmtree(syncDir + "/" + session + "/" + directory + "/")
        
        for session in os.listdir(syncDir):
            if "SESSION000" != session and os.path.isdir(syncDir + "/" + session):
                for directory in os.listdir(syncDir + "/" + session):
                    if "crashes" == directory:
                        for num, filename in enumerate(os.listdir(syncDir + "/" + session + "/" + directory)):
                            src_path = syncDir + "/" + session + "/" + directory + "/" + filename
                            dst_path = syncDir + "/" + "SESSION000" + "/" + "crashes" + "/" + filename
                            if not os.path.isfile(dst_path):
                                #dst_path += "," + str(num)
                                shutil.move(src_path, dst_path)
                    if "hangs" == directory:
                        for num, filename in enumerate(os.listdir(syncDir + "/" + session + "/" + directory)):
                            src_path = syncDir + "/" + session + "/" + directory + "/" + filename
                            dst_path = syncDir + "/" + "SESSION000" + "/" + "hangs" + "/" + filename
                            if not os.path.isfile(dst_path):
                                #dst_path += "," + str(num)
                                shutil.move(src_path, dst_path)
                    if "queue" == directory:
                        for num, filename in enumerate(os.listdir(syncDir + "/" + session + "/" + directory)):
                            src_path = syncDir + "/" + session + "/" + directory + "/" + filename
                            dst_path = syncDir + "/" + "SESSION000" + "/" + "queue" + "/" + filename
                            if os.path.isdir(src_path):
                                continue
                            if not os.path.isfile(dst_path):
                                #dst_path += "," + str(num)
                                shutil.move(src_path, dst_path)
                shutil.rmtree(syncDir + "/" + session)
                
        return True
                
    def _minimize_sync(self, jobId):
        job_config = ConfigParser.ConfigParser()
        job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")

        launch = ""
        if os.path.exists(self._config['orthrus']['directory'] + "/binaries/afl-harden"):
            launch = self._config['orthrus']['directory'] + "/binaries/afl-harden/bin/" + job_config.get(jobId, "target") + " " + job_config.get(jobId, "params").replace("&","\&")
        else:
            launch = self._config['orthrus']['directory'] + "/binaries/afl-asan/bin/" + job_config.get(jobId, "target") + " " + job_config.get(jobId, "params").replace("&","\&")
        
        export = {}
        export['PYTHONUNBUFFERED'] = "1"
        env = os.environ.copy()
        env.update(export)
        cmin = " ".join(["afl-minimize", "-c", self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect", "--cmin", "--cmin-mem-limit=800", "--cmin-timeout=5000", "--dry-run", self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out", "--", "'" + launch + "'"])
        p = subprocess.Popen(cmin, bufsize=0, shell=True, executable='/bin/bash', env=env, stdout=subprocess.PIPE)
        for line in p.stdout:
            if "[*]" in line or "[!]" in line:
                util.color_print("\t\t\t" + line)
        seed_cmd = " ".join(["afl-minimize", "-c", self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin", "--reseed", self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out", "--", "'" + launch + "'"])
        p = subprocess.Popen(seed_cmd, bufsize=0, shell=True, executable='/bin/bash', env=env, stdout=subprocess.PIPE)
        for line in p.stdout:
            if "[*]" in line or "[!]" in line:
                util.color_print("\t\t\t" + line)
                        
        if os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect"):
            shutil.rmtree(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect")
        if os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin"):
            shutil.rmtree(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin")
        if os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin.crashes"):
            shutil.rmtree(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin.crashes")
        if os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin.hangs"):
            shutil.rmtree(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/collect.cmin.hangs")
            
        return True
     
    def _start_afl_coverage(self, jobId):
        job_config = ConfigParser.ConfigParser()
        job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
        
        target = self._config['orthrus']['directory'] + "/binaries/coverage/fuzzing/bin/" + job_config.get(jobId, "target") + " " + job_config.get(jobId, "params").replace("@@","AFL_FILE")
        cmd = [self._config['afl-cov']['afl_cov_path'] + "/afl-cov", "-d", ".orthrus/jobs/" + jobId + "/afl-out", "--live", "--lcov-path", "/usr/bin/lcov", "--coverage-cmd", "'" + target + "'", "--code-dir", ".", "-v"]
        logfile = open(self._config['orthrus']['directory'] + "/logs/afl-coverage.log", "w")
        print " ".join(cmd)
        p = subprocess.Popen(" ".join(cmd), shell=True, stdout=logfile, stderr=subprocess.STDOUT)
        
        return True

        
    def run(self):
        util.color_print(util.bcolors.BOLD + util.bcolors.HEADER + "[+] Starting fuzzing jobs" + util.bcolors.ENDC + "\n")
        
        util.color_print("\t\t[+] Check Orthrus workspace... ")
        sys.stdout.flush()
        if not os.path.exists(self._config['orthrus']['directory'] + "/jobs/jobs.conf"):
            util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
        if os.path.getsize(self._config['orthrus']['directory'] + "/jobs/jobs.conf") < 1:
            util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
        util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
        
        job_config = ConfigParser.ConfigParser()
        job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
        
        if self._args.job_id:
            jobId = self._args.job_id
            total_cores = self._get_cpu_core_info()
            if jobId in job_config.sections():
                if len(os.listdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out/")) > 0:
                    util.color_print("\t\t[+] Tidy fuzzer sync dir... ")
                    sys.stdout.flush()
                    if not self._tidy_sync_dir(jobId):
                        util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
                        return False
                    util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
                    
                    if self._args.minimize:
                        util.color_print("\t\t[+] Minimize fuzzer sync dir... \n")
                        if not self._minimize_sync(jobId):
                            return False
                if self._args.coverage:
                    util.color_print("\t\t[+] Start afl-cov for Job [" + jobId +"]... ")
                    sys.stdout.flush()
                    if not self._start_afl_coverage(jobId):
                        util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
                        return False
                    util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
                
                util.color_print("\t\t[+] Start Fuzzers for Job [" + jobId +"]... ")
                sys.stdout.flush()
                if not self._start_fuzzers(jobId, total_cores):
                    subprocess.call("afl-multikill")
                    util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
                    return False
            
        return True
    
class OrthrusStop(object):
    
    def __init__(self, args, config):
        self._args = args
        self._config = config
    
    def run(self):
        util.color_print(util.bcolors.BOLD + util.bcolors.HEADER + "Stopping fuzzing jobs:" + util.bcolors.ENDC + "\n")
        p = subprocess.Popen("afl-multikill", shell=True, stdout=subprocess.PIPE)
        p.wait()
        output = p.communicate()[0]
        util.color_print("\t" + "\n".join(output.splitlines()[2:]))
        
        job_config = ConfigParser.ConfigParser()
        job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
            
        if self._args.minimize:
            pass
                    
        util.color_print("\n")
        
        return True
    
class OrthrusShow(object):
    
    def __init__(self, args, config):
        self._args = args
        self._config = config
    
    def run(self):
        job_config = ConfigParser.ConfigParser()
        job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
        if self._args.jobs:
            util.color_print(util.bcolors.BOLD + util.bcolors.HEADER + "Configured jobs found:" + util.bcolors.ENDC + "\n")
            for num, section in enumerate(job_config.sections()):
                t = job_config.get(section, "target")
                p = job_config.get(section, "params")
                util.color_print("\t" + str(num) + ") [" + section + "] " + t + " " + p + "\n")
        else:
            util.color_print(util.bcolors.BOLD + util.bcolors.HEADER + "Status of jobs:" + util.bcolors.ENDC + "\n")
            
            for jobId in job_config.sections():
                syncDir = self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out/"
                output = subprocess.check_output(["afl-whatsup", "-s", syncDir])
                output = output[output.find("==\n\n") + 4:]
                
                util.color_print(util.bcolors.OKBLUE + "\tJob [" + jobId + "] " + "for target '" + job_config.get(jobId, "target") + "':\n" + util.bcolors.ENDC)
                for line in output.splitlines():
                    util.color_print("\t" + line + "\n")
                triaged_unique = 0
                if os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/"):
                    triaged_unique = len(os.listdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/"))
                util.color_print("\t     Triaged crashes : " + str(triaged_unique) + " available\n")
                
        return True

class DedubThread(threading.Thread):
    def __init__(self, thread_id, timeout_secs, target_cmd, in_queue, hashes, in_queue_lock, hashes_lock, outDir, mode, jobId):
        threading.Thread.__init__(self)
        self.id = thread_id
        self.timeout_secs = timeout_secs
        self.target_cmd = target_cmd
        self.in_queue = in_queue
        self.hashes = hashes
        self.in_queue_lock = in_queue_lock
        self.hashes_lock = hashes_lock
        self.outDir = outDir
        self.mode = mode
        self.jobId = jobId
        self.exit = False
        
    def run(self):
        while not self.exit:
            self.in_queue_lock.acquire()
            if not self.in_queue.empty():
                sample = self.in_queue.get()
                self.in_queue_lock.release()
                sample = os.path.abspath(sample)
                cmd = ""
                in_file = None
                if "@@" in self.target_cmd:
                    cmd = self.target_cmd.replace("@@", sample)
                else:
                    cmd = self.target_cmd
                    in_file = open(sample, "rb")
                    
#                 try:
                env = os.environ.copy()
                asan_flag = {}
                asan_flag['ASAN_OPTIONS'] = "abort_on_error=1:disable_coredump=1:symbolize=0"
                env.update(asan_flag)
                
                dev_null = open(os.devnull, "r+")
                output = ""
                p = subprocess.Popen(cmd, shell=True, executable="/bin/bash", env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=dev_null)
                if in_file:
                    output = p.communicate(in_file.read())[0]
                else:
                    output = p.communicate()[0]
                dev_null.close()
                output = output[output.find("Hash: ") + 6:]
                crash_hash = output[:output.find(".")]
                
                self.hashes_lock.acquire()
                if crash_hash in self.hashes:
                    self.hashes_lock.release()
                    os.remove(sample)
                else:
                    self.hashes.add(crash_hash)
                    self.hashes_lock.release()

                    shutil.copy(sample, self.outDir + self.mode + ":" + self.jobId + "," + os.path.basename(sample))
#                 except Exception:
                if in_file:
                    in_file.close()
            else:
                self.in_queue_lock.release()
                self.exit = True
                
class OrthrusTriage(object):
    
    def __init__(self, args, config):
        self._args = args
        self._config = config
    
    def _add_crash_to_crash_graph(self, jobId, crash_file):
        job_config = ConfigParser.ConfigParser()
        job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
        
        dev_null = open(os.devnull, "w")
        logfile = open(self._config['orthrus']['directory'] + "/logs/crash_graph_add.log", "a")
        if "HARDEN" in crash_file:
            if not os.path.exists(self._config['orthrus']['directory'] + "/binaries/harden-dbg"):
                return False
            p1_cmd = " ".join(["gdb", "-q", "-ex='set args " + job_config.get(jobId, "params").replace("@@", crash_file) + "'", "-ex='run'", "-ex='orthrus'", "-ex='quit'", "--args", self._config['orthrus']['directory'] + "/binaries/harden-dbg/bin/" + job_config.get(jobId, "target")])
            p1 = subprocess.Popen(p1_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=dev_null)
            
            p2_cmd = "joern-runtime-info -r -v -g -l"
            p2 = subprocess.Popen(p2_cmd, shell=True, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT)
            p2.communicate(p1.stdout.read())
            p2.wait()
            
        elif "ASAN" in crash_file:
            if not os.path.exists(self._config['orthrus']['directory'] + "/binaries/asan-dbg"):
                return False
            p1_cmd = "ulimit -c 0; " + self._config['orthrus']['directory'] + "/binaries/asan-dbg/bin/" + job_config.get(jobId, "target") + " " + job_config.get(jobId, "params").replace("@@", crash_file)
            export = {}
            export['ASAN_SYMBOLIZER_PATH'] = "/usr/local/bin/llvm-symbolizer"
            export['ASAN_OPTIONS'] = "abort_on_error=1:symbolize=1:print_cmdline=1:disable_coredump=1"
            env = os.environ.copy()
            env.update(export)
            p1 = subprocess.Popen(p1_cmd, shell=True, executable="/bin/bash", env=env, stdout=dev_null, stderr=subprocess.PIPE)

            p2_cmd = "joern-runtime-info -r -v -g -l"
            # Injecting the command line string ist a hack for gcc, there the ASAN option 'print_cmdline' is not available.
            # Plus, Gdb offers only a truncated command line string
            cmdline = "Command: " + self._config['orthrus']['directory'] + "/binaries/asan-dbg/bin/" + job_config.get(jobId, "target") + " " + job_config.get(jobId, "params").replace("@@", crash_file)
            p2 = subprocess.Popen(p2_cmd, shell=True, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT)
            p2.communicate(p1.stderr.read() + cmdline)
            p2.wait()
            
        dev_null.close()
        logfile.close()
        
        return True
    
    def _triage_crash_graph(self, jobIds):
        job_config = ConfigParser.ConfigParser()
        job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
        
        logfile = open(self._config['orthrus']['directory'] + "/logs/crash_graph_triage.log", "a")
        
        cmd = "joern-runtime-info -r -v -g --triage"
        p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        output = p.communicate("")[0]
        logfile.write(output)
        output = output[output.find("Triaged set:"):]
        output = output[output.find("\n") + 1:]
        
        keep_list = output.splitlines()
        for jobId in jobIds:
            samples = os.listdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/")
            for filename in samples:
                if filename not in keep_list:
                    if os.path.isfile(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/" + filename):
                        os.remove(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/" + filename)
        
        logfile.close()
        
        return True
            
    def deduplicate_crashes(self, jobId, samples, mode, num_threads):
        target_cmd = ""
        in_queue_lock = threading.Lock()
        hashes_lock = threading.Lock()
        hashes = set()
        in_queue = Queue(len(samples))
        
        job_config = ConfigParser.ConfigParser()
        job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
            
        outDir = self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/"
        # fill input queue with samples
        in_queue_lock.acquire()
        for s in samples:
#             print s
            in_queue.put(s)
        in_queue_lock.release()
        
        if mode == "HARDEN":
            target_cmd = " ".join(["gdb", "-q", "-ex='set args " + job_config.get(jobId, "params") + "'", "-ex='run'", "-ex='orthrus'", "-ex='quit'", "--args", self._config['orthrus']['directory'] + "/binaries/harden-dbg/bin/" + job_config.get(jobId, "target")])
        elif mode == "ASAN":
            target_cmd = " ".join(["gdb", "-q", "-ex='set args " + job_config.get(jobId, "params") + "'", "-ex='run'", "-ex='orthrus'", "-ex='quit'", "--args", self._config['orthrus']['directory'] + "/binaries/asan-dbg/bin/" + job_config.get(jobId, "target")])

        
        thread_list = []
        for i in range(0, num_threads, 1):
#             print "Start thread: " + str(i)
            t = DedubThread(i, 10, target_cmd, in_queue, hashes, in_queue_lock, hashes_lock, outDir, mode, jobId)
            thread_list.append(t)
            t.daemon = True
            t.start()
        
        for t in thread_list:
            t.join()
            
        return True
    
    def _remove_cg_graph(self):
        cmd = " ".join(["joern-runtime-info", "-g -u"])
        p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        output = p.communicate("")[0]
        if not output:
            return False
        else:
            return True
        
    def run(self):
        job_config = ConfigParser.ConfigParser()
        job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
        
        jobIds = []
        if self._args.job_id:
            jobIds[0] = self._args.job_id
        else:
            jobIds = job_config.sections()
            
        for jobId in jobIds:
            util.color_print(util.bcolors.BOLD + util.bcolors.HEADER + "[+] Triaging crashes for job [" + jobId + "]" + util.bcolors.ENDC + "\n")
            
            if not os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/"):
                os.mkdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/")
            else:
                util.color_print("[?] Rerun triaging? [y/n]...: ")
                sys.stdout.flush()
                if 'y' not in sys.stdin.readline()[0]:
                    return True
                shutil.move(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/", self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique." + time.strftime("%Y-%m-%d-%H:%M:%S"))
                self._remove_cg_graph()
                os.mkdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/")
                 
            if os.path.exists(self._config['orthrus']['directory'] + "/binaries/afl-harden"):
                util.color_print("\t\t[+] Collect and verify 'harden' mode crashes... ")
                sys.stdout.flush()
                      
                syncDir = self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out/"
                outDir = self._config['orthrus']['directory'] + "/jobs/" + jobId + "/crash_harden"
                launch = self._config['orthrus']['directory'] + "/binaries/harden-dbg/bin/" + job_config.get(jobId, "target") + " " + job_config.get(jobId, "params").replace("&","\&")
                cmd = " ".join(["afl-collect", "-r", "-j 2", syncDir, outDir, "--", launch])
                logfile = open(os.devnull, "w")
                p = subprocess.Popen("ulimit -c 0; " + cmd, shell=True, stdout=logfile, stderr=subprocess.STDOUT)
                p.wait()
                logfile.close()
                util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
                      
            if os.path.exists(self._config['orthrus']['directory'] + "/binaries/afl-asan"):
                util.color_print("\t\t[+] Collect and verify 'asan' mode crashes... ")
                sys.stdout.flush()
                      
                env = os.environ.copy()
                asan_flag = {}
                asan_flag['ASAN_OPTIONS'] = "abort_on_error=1:disable_coredump=1:symbolize=0"
                env.update(asan_flag)
                syncDir = self._config['orthrus']['directory'] + "/jobs/" + jobId + "/afl-out/"
                outDir =self._config['orthrus']['directory'] + "/jobs/" + jobId + "/crash_asan"
                launch = self._config['orthrus']['directory'] + "/binaries/asan-dbg/bin/" + job_config.get(jobId, "target") + " " + job_config.get(jobId, "params").replace("&","\&")
                cmd = " ".join(["afl-collect", "-r", "-j 2", syncDir, outDir, "--", launch])
                logfile = open(os.devnull, "w")
                p = subprocess.Popen(cmd, shell=True, executable="/bin/bash", env=env, stdout=logfile, stderr=subprocess.STDOUT)
                p.wait()
                logfile.close()
                util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
                      
            if os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/crash_harden/"):
                util.color_print("\t\t[+] Deduplicate 'harden' mode crashes... ")
                sys.stdout.flush()
                      
                crash_files = os.listdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/crash_harden/")
                for num, crash_file in enumerate(crash_files):
                    crash_files[num] = self._config['orthrus']['directory'] + "/jobs/" + jobId + "/crash_harden/" + crash_file
                        
                if not self.deduplicate_crashes(jobId, crash_files, "HARDEN", 2):
                    util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
                shutil.rmtree(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/crash_harden/")
                util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
                        
            if os.path.exists(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/crash_asan/"):
                util.color_print("\t\t[+] Deduplicate 'asan' mode crashes... ")
                sys.stdout.flush()
                       
                crash_files = os.listdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/crash_asan/")
                for num, crash_file in enumerate(crash_files):
                    crash_files[num] = self._config['orthrus']['directory'] + "/jobs/" + jobId + "/crash_asan/" + crash_file
                         
                if not self.deduplicate_crashes(jobId, crash_files, "ASAN", 2):
                    util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
                shutil.rmtree(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/crash_asan/")
                util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
                   
            dedub_crashes = os.listdir(self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/")
            util.color_print("\t\t[+] Upload " + str(len(dedub_crashes)) + " crashes to database for further triaging... ")
            sys.stdout.flush()
            if not dedub_crashes:
                util.color_print(util.bcolors.OKBLUE + "nothing to do" + util.bcolors.ENDC + "\n")
                return
            util.color_print("\n")
               
            for crash in dedub_crashes:
                util.color_print("\t\t\t[+] Adding " + crash + " ... ")
                sys.stdout.flush()
                if not self._add_crash_to_crash_graph(jobId, self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/" + crash):
                    util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
                    continue
                util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
                  
        util.color_print("\t\t[+] Triaging crashes... ")
        sys.stdout.flush()
        if not self._triage_crash_graph(jobIds):
            util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
            return
        util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            
        return True

class OrthrusDatabase(object):
    
    def __init__(self, args, config):
        self._args = args
        self._config = config
    
    def _start_joern(self, binary, configfile):
        export = {}
        export['wrapper_java_additional'] = "-Dorg.neo4j.server.properties=" + configfile
        env = os.environ.copy()
        env.update(export)
        command = binary + " start"
        p = subprocess.Popen(command, shell=True, executable='/bin/bash', env=env, stdout=subprocess.PIPE)
        p.wait()
        #util.color_print(p.communicate()[0])
        if p.returncode != 0:
            return False
        return True
    
    def _stop_joern(self, binary):
        command = binary + " stop"
        p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
        p.wait()
        if p.returncode != 0:
            return False
        return True
    
    def _upload_crash(self, jobId, crash_file):
        job_config = ConfigParser.ConfigParser()
        job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
        
        dev_null = open(os.devnull, "w")
        logfile = open(self._config['orthrus']['directory'] + "/logs/upload.log", "a")
        if "HARDEN" in crash_file:
            if not os.path.exists(self._config['orthrus']['directory'] + "/binaries/harden-dbg"):
                return False
            p1_cmd = " ".join(["gdb", "-q", "-ex='set args " + job_config.get(jobId, "params").replace("@@", crash_file) + "'", "-ex='run'", "-ex='orthrus'", "-ex='gcore core'", "-ex='quit'", "--args", self._config['orthrus']['directory'] + "/binaries/harden-dbg/bin/" + job_config.get(jobId, "target")])
            p1 = subprocess.Popen(p1_cmd, shell=True, stdout=subprocess.PIPE, stderr=dev_null)
            
            p2_cmd = "joern-runtime-info -r -v -l"
            p2 = subprocess.Popen(p2_cmd, shell=True, stdin=p1.stdout, stdout=logfile, stderr=subprocess.STDOUT)
            p2.wait()
            
        elif "ASAN" in crash_file:
            if not os.path.exists(self._config['orthrus']['directory'] + "/binaries/asan-dbg"):
                return False
            p1_cmd = "ulimit -c 1024000; " + self._config['orthrus']['directory'] + "/binaries/asan-dbg/bin/" + job_config.get(jobId, "target") + " " + job_config.get(jobId, "params").replace("@@", crash_file)
            export = {}
            export['ASAN_SYMBOLIZER_PATH'] = "/usr/local/bin/llvm-symbolizer"
            export['ASAN_OPTIONS'] = "abort_on_error=1:symbolize=1:print_cmdline=1"
            env = os.environ.copy()
            env.update(export)
            p1 = subprocess.Popen(p1_cmd, shell=True, executable="/bin/bash", env=env, stdout=dev_null, stderr=subprocess.PIPE)

            p2_cmd = "joern-runtime-info -r -v -l"
            # Injecting the command line string ist a hack for gcc, there the ASAN option 'print_cmdline' is not available.
            # Plus, Gdb offers only a truncated command line string
            cmdline = "Command: " + self._config['orthrus']['directory'] + "/binaries/asan-dbg/bin/" + job_config.get(jobId, "target") + " " + job_config.get(jobId, "params").replace("@@", crash_file)
            p2 = subprocess.Popen(p2_cmd, shell=True, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT)
            p2.communicate(p1.stderr.read() + cmdline)
            p2.wait()
            
        dev_null.close()
        logfile.close()
        
        return True
    
    def _unload_crash(self, pid):
        cmd = " ".join(["joern-runtime-info", "-v -u"])
        p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        
        output = p.communicate(pid)[0]
        if not output:
            return False
        else:
            for line in output.splitlines():
                if pid in line:
                    return True
        
        return False
        
    def _get_all_crash_pids(self):
        query = "queryNodeIndex('type:RtCrash').pid"
        
        cmd = " ".join(["joern-lookup", "-g"])
        p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        
        output = p.communicate(query)[0]
        if not output:
            return []
        else:
            return output.splitlines()
        
    def run(self):
        util.color_print(util.bcolors.BOLD + util.bcolors.HEADER + "[+] Performing database operation" + util.bcolors.ENDC + "\n")
        
        if self._args.startup:
            util.color_print(util.bcolors.BOLD + util.bcolors.HEADER + "\t[+] Joern Neo4j database" + util.bcolors.ENDC + "\n")
            
            util.color_print("\t\t[+] Check Orthrus workspace... ")
            sys.stdout.flush()
            if not os.path.exists(self._config['orthrus']['directory'] + "/conf/neo4j-server.properties"):
                util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
            util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            
            util.color_print("\t\t[+] Starting Joern Neo4j database instance... ")
            sys.stdout.flush()
            configfile = os.path.abspath(self._config['orthrus']['directory'] + "/conf/neo4j-server.properties")
            if not self._start_joern(self._config['neo4j']['neo4j_path'] + "/bin/neo4j", configfile):
                util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
                return False
            util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            
            return True
        
        if self._args.shutdown:
            util.color_print(util.bcolors.BOLD + util.bcolors.HEADER + "\t[+] Joern Neo4j database" + util.bcolors.ENDC + "\n")
            
            util.color_print("\t\t[+] Stopping Joern Neo4j database instance... ")
            sys.stdout.flush()
            if not self._stop_joern(self._config['neo4j']['neo4j_path'] + "/bin/neo4j"):
                util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
                return False
            util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            
            return True
        
        if self._args.load_crashes:
            job_config = ConfigParser.ConfigParser()
            job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
            if self._args.all:
                return False
            elif self._args.job_id:
                jobId = self._args.job_id
                util.color_print("\t[+] Checking triaged crash samples... ")
                sys.stdout.flush()
                
                uniqueDir = self._config['orthrus']['directory'] + "/jobs/" + jobId + "/unique/"
                
                if not os.path.exists(uniqueDir) or not len(os.listdir(uniqueDir)):
                    util.color_print(util.bcolors.WARNING + "no crashes" + util.bcolors.ENDC + "\n")
                    return True
                util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
                
                crashes = os.listdir(uniqueDir)
                util.color_print("\t[+] Processing " + str(len(crashes)) + " crash samples... \n")
                
                for crash in crashes:
                    crash_path = uniqueDir + crash
                    util.color_print("\t\t[+] Upload crash " + crash + "... ")
                    sys.stdout.flush()
                    if not self._upload_crash(jobId, crash_path):
                        util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
                        continue
                    util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            else:
                return False
        elif self._args.unload_crashes:
            job_config = ConfigParser.ConfigParser()
            job_config.read(self._config['orthrus']['directory'] + "/jobs/jobs.conf")
            if self._args.all:
                util.color_print("\t[+] Removing all crash nodes from database... ")
                sys.stdout.flush()
                
                pids = self._get_all_crash_pids()
                if not pids:
                    util.color_print(util.bcolors.WARNING + "no crashes" + util.bcolors.ENDC + "\n")
                    return True
                util.color_print(util.bcolors.OKBLUE + "found " + str(len(pids)) + " crashes" + util.bcolors.ENDC + "\n")
                
                for pid in pids:
                    util.color_print("\t\t[+] Removing crash for PID " + pid + "... ")
                    sys.stdout.flush()
                    if not self._unload_crash(pid):
                        util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
                        continue
                    util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
                return True
            elif self._args.job_id:
                return False
            
        if self._args.load_coverage:
            pass
        
        return True
    
class OrthrusDestroy(object):
    
    def __init__(self, args, config):
        self._args = args
        self._config = config
    
    def run(self):
        util.color_print(util.bcolors.BOLD + util.bcolors.HEADER + "[+] Destroy Orthrus workspace" + util.bcolors.ENDC + "\n")
        util.color_print("[?] Delete complete workspace? [y/n]...: ")
        sys.stdout.flush()
        if 'y' not in sys.stdin.readline()[0]:
            return True
        
        util.color_print("\t\t[+] Deleting all files... ")
        sys.stdout.flush() 
        if not os.path.exists(self._config['orthrus']['directory']):
            util.color_print(util.bcolors.OKBLUE + "destroyed already" + util.bcolors.ENDC + "\n")
        else:
            shutil.rmtree(self._config['orthrus']['directory'])
            if not os.path.isdir(self._config['orthrus']['directory']):
                util.color_print(util.bcolors.OKGREEN + "done" + util.bcolors.ENDC + "\n")
            else:
                util.color_print(util.bcolors.FAIL + "failed" + util.bcolors.ENDC + "\n")
        return
