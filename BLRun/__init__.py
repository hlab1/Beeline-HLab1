"""
BEELINE Run (:mod:`BLRun`) module contains the following main class:

- :class:`BLRun.BLRun` and three additional classes used in the definition of BLRun class

- :class:`BLRun.ConfigParser`
- :class:`BLRun.InputSettings`
- :class:`BLRun.OutputSettings`

"""

import yaml
import argparse
import itertools
from collections import defaultdict
from pathlib import Path
import multiprocessing
from multiprocessing import Pool, cpu_count
import concurrent.futures
from typing import Dict, List
import yaml
import argparse
import itertools
from collections import defaultdict
from pathlib import Path
import multiprocessing
from multiprocessing import Pool, cpu_count
import concurrent.futures
from typing import Dict, List
from BLRun.runner import Runner
import os
import pandas as pd


class InputSettings(object):
    def __init__(self,
                 datadir, fulldatadir, datasets, algorithms, sifdir, overlaydir, gpuflag) -> None:
        self.datadir = datadir
        self.fulldatadir = fulldatadir
        self.datasets = datasets
        self.algorithms = algorithms
        self.sifdir = sifdir
        self.overlaydir = overlaydir
        self.gpuflag = gpuflag


class OutputSettings(object):
    '''
    Structure for storing the names of directories that output should
    be written to
    '''

    def __init__(self, base_dir, output_prefix: Path) -> None:
        self.base_dir = base_dir
        self.output_prefix = output_prefix

class BLRun(object):
    '''
    The BLRun object is created by parsing a user-provided configuration
    file. Its methods provide for further processing its inputs into
    a series of jobs to be run, as well as running these jobs.
    '''

    def __init__(self,
            input_settings: InputSettings,
            output_settings: OutputSettings) -> None:

        self.input_settings = input_settings
        self.output_settings = output_settings
        self.runners: Dict[int, Runner] = self.__create_runners()


    def __create_runners(self) -> Dict[int, List[Runner]]:
        '''
        Instantiate the set of runners based on parameters provided via the
        configuration file. Each runner is supplied an interactome, collection,
        the set of algorithms to be run, and graphspace credentials, in
        addition to the custom parameters each runner may or may not define.
        '''
        
        runners: Dict[int, Runner] = defaultdict(list)
        order = 0
        for dataset in self.input_settings.datasets:
            print('=====Using dataset '+dataset['name'])
            for runner in self.input_settings.algorithms:
                data = {}
                data['name'] = runner[0]
                data['params'] = runner[1]
                if (len(runner)==3):
                    data['dataset_params'] = runner[2]
                data['inputDir'] = Path.cwd().joinpath(self.input_settings.datadir.joinpath(dataset['name']))
                data['fullInputDir'] = Path.cwd().joinpath(self.input_settings.fulldatadir.joinpath(dataset['name']))
                data['singularityImage'] = str(self.input_settings.sifdir) + '/' + data['name'] + '.sif'
                data['singularityOverlay'] = str(self.input_settings.overlaydir) + '/' + data['name'] + '.ext3'
                data['singularityGPUFlag'] = self.input_settings.gpuflag
                data['datasetName'] = dataset['name']
                data['exprData'] = dataset['exprData']
                data['cellData'] = dataset['cellData']
                data['trueEdges'] = dataset['trueEdges']
                # optional values
                for opt_k in ['exprDataIdMap','exprDataIdMapType']:
                    if opt_k in dataset:
                        data[opt_k] = dataset[opt_k]

                if 'should_run' in data['params'] and \
                        data['params']['should_run'] is False:
                    print("Skipping %s" % (data['name']))
                    continue
                else:
                    print("Running %s" % (data['name']))

                runners[order] = Runner(data)
                order += 1            
        return runners


    def execute_runners(self, parallel=False, num_threads=1):
        '''
        Run each of the algorithms
        '''

        base_output_dir = self.output_settings.base_dir

        batches =  self.runners.keys()

        for batch in batches:
            if parallel==True:
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                futures = [executor.submit(runner.run, base_output_dir)
                    for runner in self.runners[batch]]
                
                # https://stackoverflow.com/questions/35711160/detect-failed-tasks-in-concurrent-futures
                # Re-raise exception if produced
                for future in concurrent.futures.as_completed(futures):
                    future.result()
                executor.shutdown(wait=True)
            else:
                for runner in self.runners[batch]:
                    runner.run(output_dir=base_output_dir)
                    
                    
class ConfigParser(object):
    '''
    Define static methods for parsing a config file that sets a large number
    of parameters for the pipeline
    '''
    @staticmethod
    def parse(config_file_handle,cmd_args) -> BLRun:
        config_map = yaml.load(config_file_handle)
        return BLRun(
            ConfigParser.__parse_input_settings(
                config_map['input_settings'],
                cmd_args),
            ConfigParser.__parse_output_settings(
                config_map['output_settings']))

    @staticmethod
    def __parse_input_settings(input_settings_map,cmd_args) -> InputSettings:
        input_dir = input_settings_map['input_dir']
        dataset_dir = input_settings_map['dataset_dir']
        full_dataset_dir = input_settings_map['full_dataset_dir']
        datasets_all = input_settings_map['datasets']
        sif_dir = input_settings_map['sif_dir']
        overlay_dir = input_settings_map['overlay_dir']
        gpu_flag = input_settings_map['gpu_flag']
        algorithms_all = input_settings_map['algorithms']
        
        datasets_select = [] if cmd_args.dataset_names is None else cmd_args.dataset_names.split(',')
        datasets = []
        for dataset in datasets_all:
            # if subset was specified, add each 
            # if subset was not specified, add all the datasets
            if (len(datasets_select)>0):
                if (dataset['name'] in datasets_select):
                    datasets.append(dataset)
            else:
               datasets.append(dataset)
        algorithms_select = [] if cmd_args.algorithm_names is None else cmd_args.algorithm_names.split(',')
        algorithm_list = []
        for algorithm in algorithms_all:
            # if subset was specified, change each should_run to True and others to False
            # if subset was not specified, just add the original algorithm setting
            if (len(algorithms_select)>0):
                if (algorithm['name'] in algorithms_select):
                    algorithm['params']['should_run'] = [True]
                else:
                    algorithm['params']['should_run'] = [False]
            algorithm_list.append(algorithm)

        print(datasets_select)
        print(algorithms_select)
        print(len(dataset))
        print(len(algorithm_list))
            
        return InputSettings(
                Path(input_dir, dataset_dir),
                Path(input_dir, full_dataset_dir),
                datasets,
                ConfigParser.__parse_algorithms(
                    algorithm_list),
                Path(sif_dir),
                Path(overlay_dir),
                gpu_flag
        )


    @staticmethod
    def __parse_algorithms(algorithms_list):
        algorithms = []
        for algorithm in algorithms_list:
                combos = [dict(zip(algorithm['params'], val))
                    for val in itertools.product(
                        *(algorithm['params'][param]
                            for param in algorithm['params']))]
                for combo in combos:
                    if 'dataset_params' in algorithm:
                        algorithms.append([algorithm['name'],combo,algorithm['dataset_params']])
                    else:
                        algorithms.append([algorithm['name'],combo])

        return algorithms

    @staticmethod
    def __parse_output_settings(output_settings_map) -> OutputSettings:
        output_dir = Path(output_settings_map['output_dir'])
        output_prefix = Path(output_settings_map['output_prefix'])

        return OutputSettings(output_dir,
                             output_prefix)





                    
