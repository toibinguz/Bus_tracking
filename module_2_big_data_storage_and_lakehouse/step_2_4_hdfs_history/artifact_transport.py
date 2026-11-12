"""Bounded private-network WebHDFS transport for many small domain artifacts."""
import json
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener
from uuid import uuid4

from .webhdfs import WebHdfsUploader, _NoRedirect


class PrivateWebHdfs:
    def __init__(self):
        self.client=WebHdfsUploader('http://namenode:9870')

    def url(self,path,operation):
        if path.startswith('hdfs://namenode:8020'):
            path=path[len('hdfs://namenode:8020'):]
        if not path.startswith('/bus-eta/v1/'):
            raise ValueError('unexpected artifact namespace')
        return self.client._url(path,operation)

    def exists(self,path):
        try:
            with build_opener().open(self.url(path,'GETFILESTATUS'),timeout=20) as response:
                json.loads(response.read())['FileStatus']
            return True
        except HTTPError as error:
            if error.code==404:
                return False
            raise

    def read(self,path):
        with build_opener().open(self.url(path,'OPEN'),timeout=20) as response:
            return response.read()

    def create(self,path,content):
        temporary=path+'.upload-'+str(uuid4())
        request=Request(self.url(temporary,'CREATE&overwrite=false'),data=b'',method='PUT')
        try:
            build_opener(_NoRedirect()).open(request,timeout=20)
        except HTTPError as error:
            if error.code!=307:
                raise
            location=error.headers['Location']
        else:
            raise RuntimeError('expected DataNode redirect')
        with build_opener().open(Request(location,data=content,method='PUT'),timeout=20):
            pass
        destination=path[len('hdfs://namenode:8020'):] if path.startswith('hdfs://namenode:8020') else path
        with build_opener().open(Request(self.url(temporary,'RENAME&destination='+quote(destination,safe='')),data=b'',method='PUT'),timeout=20) as response:
            if not json.loads(response.read())['boolean']:
                raise RuntimeError('immutable artifact rename failed')
