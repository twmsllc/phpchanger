import json, sys, os, warnings, tempfile, urllib
from getpass import getuser
from subprocess import Popen, PIPE, call
from Log import Logger

logger = Logger()

class API():
    def __init__(self, parser_args):
        self.current_user = getuser()
        self.args = parser_args

    ### GENERAL API METHODS ####
    
    def unescape(self, s):
         s = s.replace('&lt;', '<')
         s = s.replace('&gt;', '>')
         s = s.replace('&quot;', '"')
         # this has to be last:
         s = s.replace('&amp;', '&')
         return s

    def format_title(self, title):
        title = '#   ' + title + '   #'
        h_border = '{s:{c}^{n}}'.format(s='#', n=len(title), c='#')
        print("\n" + h_border + "")
        print(title)
        print("" + h_border + "\n")

    def check_api_return_for_issues(self, api_return, cmd_type):
        if cmd_type == "whmapi1":
            if api_return['metadata']['version'] != 1:
                logger.log('critical', "This script not tested with whmapi version %s expected 1 instead, exiting", api_return['metadata']['version'])
                sys.exit(1)
            if api_return['metadata']['result'] != 1:
                logger.log('critical', "whmapi1 returned error flag with this reason, exiting: %s", api_return['metadata']['reason'])
                sys.exit(1)
        elif cmd_type == "uapi":
            if api_return['apiversion'] != 3:
                logger.log('critical', "This script not tested with uapi version %s expected 3 instead, exiting." , api_return['apiversion'])
                sys.exit(1)
            if api_return['result']['errors'] is not None:
                logger.log('citical', "uapi returned this error, exiting: %s", '\n'.join(error for error in api_return))
                sys.exit(1)
            if api_return['result']['messages'] is not None:
                logger.log('warning', "uapi returned this message: %s", '\n'.join(message for message in api_return['result']['messages']))
            if api_return['result']['warnings'] is not None:
                logger.log('warning', "uapi returned this warning: %s", '\n'.join(warning for warning in api_return['result']['warnings']))
        else:
            logger.log("critical", "Unrecognized cmd_type, can't check.")

    def call(self, api,cmd='',params=[],module=None, user=''):
        if api == 'whmapi1' and self.current_user != 'root':
            logger.log("critical", 'WHMAPI1 commands must be run as root.')
            sys.exit(1)
        if api == 'whmapi1' and self.current_user == 'root':
            popenargs = [api, cmd, '--output=json'] + params
        if api == 'uapi' and self.current_user == 'root':
            popenargs = [api, '--user=' + user, module, cmd, '--output=json'] + params
        if api == 'uapi' and self.current_user !='root':
            popenargs = [api, module, cmd, '--output=json'] + params
        if api != 'uapi' and api != 'whmapi1':
            logger.log('critical', 'invalid api type')
            sys.exit(1)
            
        data, error = Popen(popenargs, stdout=PIPE,stderr=PIPE).communicate()
        
        if error == '':
            data = json.loads(data)
            logger.log('info', 'Command Return Data: %s', data)
            self.check_api_return_for_issues(data, api)
            return(data)
        else:
            logger.log('critical', '%s Command Failed to Run', api)
            sys.exit(1)

    def get_php_id(self):
        if self.args.version:
            installed_php_versions = self.get_installed_php_versions()
            # if user gave us digits, prefix ea-php, else we assume the user gave a full php ID.
            try:
                php_id = "ea-php" + str(int(self.args.version))
            except ValueError:
                php_id = self.args.version
                logger.log('info', 'Selected PHP version : %s', php_id)
            if php_id in installed_php_versions or php_id == "inherit":
                return "version=" + php_id
            else:
                sys.exit("Provided PHP version " + php_id + " is not installed. Currently installed:\n" + '\n'.join(installed_php_versions))

    def get_installed_php_versions(self):
        if self.current_user == 'root':
            installed_php_versions = self.call("whmapi1", cmd="php_get_installed_versions")
            logger.log('info','Installed PHP versions: %s', installed_php_versions['data']['versions'])
            return installed_php_versions['data']['versions']
        else:
            installed_php_versions = self.call("uapi", module="LangPHP", cmd="php_get_installed_versions")
            logger.log('info','Installed PHP versions: %s', installed_php_versions['result']['data']['versions'])
            return installed_php_versions['result']['data']['versions']

    def breakup_domains_by_users(self):
        users_domains = {}
        i = 0
        while i < len(self.args.domains):
            domain = self.args.domains[i]
            if self.current_user == 'root':
                user = self.call('whmapi1', cmd='getdomainowner',params=['domain=' + domain])['data']['user']
            else:
                if self.current_user_owns_this_domain(domain):
                    user = self.current_user
                else:
                    user = None

            if user is not None:
                users_domains[domain] = user
            else:
                logger.log("warning", " %s Either does not exist, " 
                    "or is not owned by the user calling this function --skipping",
                    domain)
            i += 1            

        return users_domains
    
    def current_user_owns_this_domain(self, domain):
        users_domains = []
        response = self.call('uapi', module='DomainInfo', 
            cmd='list_domains', user=self.current_user)
        data = response['result']['data']
        users_domains = [data['main_domain']]
        users_domains = users_domains + data['sub_domains']
        users_domains = users_domains + data['addon_domains']
        users_domains = users_domains + data['parked_domains']
        if domain in users_domains:
            return True
        else:
            return False

    ### MANAGER STUFF AND THINGS ###
        
    def manager_get(self):
        api = "uapi"
        module = "LangPHP"
        cmd = "php_get_vhost_versions"

        users_domains = self.breakup_domains_by_users()
        for domain , user in users_domains.iteritems():
            vhost_php_versions = self.call(api, user=user, cmd=cmd, module=module)
            for vhost in vhost_php_versions['result']['data']:
                if vhost['vhost'] == domain:          
                    self.format_title('VHOST: ' + vhost['vhost'])
                    if "system_default" in vhost['phpversion_source']:
                        print("PHP Version: inherit (" + vhost['version'] + ")")
                    else:
                        print("PHP Version: " + vhost['version'])
                    print("PHP-FPM Status: " + ("Enabled" if vhost['php_fpm'] == 1 else "Disabled"))
                    if vhost['php_fpm'] == 1:
                        print("PHP-FPM Pool, Max Children: " + str(vhost['php_fpm_pool_parms']['pm_max_children']))
                        print("PHP-FPM Pool, Process Idle Timeout: " + str(vhost['php_fpm_pool_parms']['pm_process_idle_timeout']))
                        print("PHP-FPM Pool, Max Requests: " + str(vhost['php_fpm_pool_parms']['pm_max_requests']) + "\n")
                
    def manager_set(self):
        cmd = "php_set_vhost_versions"
        params = []
        if self.current_user == "root":    
            if isinstance(self.args.fpm, (list,)):
                if self.args.version is None:
                    logger.log('warning', "Keep in mind that PHP-FPM will fail "
                        "to enable if the PHP version is set to \"inherit\""
                        ". \nThis script doesnt check for that, hopefully you did."
                        )
                elif self.args.version == "inherit" :
                    logger.log('error', 'PHP-FPM cannot be enabled while also setting PHP version to "inherit". --skipping')
                else:
                    params=[
                        'php_fpm_pool_parms={"pm_max_children":' + \
                        self.args.fpm[0] + ',"pm_process_idle_timeout":' + \
                        self.args.fpm[1] + ',"pm_max_requests":' + \
                        self.args.fpm[2] + '}',
                        'php_fpm=1'
                    ]
            elif self.args.fpm is False:
                params ="php_fpm=0"
        
        users_domains = self.breakup_domains_by_users()
        for domain , user in users_domains.iteritems():
            logger.log('debug', 'Domain: %s :: User: %s', domain, user)
            params.append("vhost=" + domain)

        # if user gave us digits, prefix ea-php, else we assume the user gave a full php ID.
        if self.args.version is not None:
            self.php_id = self.get_php_id()
            params.append(self.php_id)

        if self.current_user == "root":
            logger.log('debug', 'Calling php_set_vhost_versions using WHMAPI1')
            self.call('whmapi1', cmd=cmd, params=params)
        else:
            logger.log('debug', 'Calling php_set_vhost_versions using UAPI')
            self.call('uapi', cmd=cmd, module='LangPHP', params=params)
        if self.current_user == "root":
            if (self.args.fpm) or (isinstance(self.args.fpm, (list,))):
                logger.log('info', 'The PHP-FPM Configuration has been updated')
        if self.args.version is not None:
            logger.log('info', 'The PHP version for the selected domains has been set to %s', self.php_id)

    ### INI STUFF AND THINGS ###                

    def ini_get(self):
        user_domains = self.breakup_domains_by_users()
        for domain, user in user_domains.iteritems():
            self.ini_getter(user, domain)

    def ini_getter(self,user,domain):
        params = ['type=vhost', 'vhost=' + domain]
        php_ini_settings = self.call('uapi', 
            user=user, module='LangPHP', 
            cmd='php_ini_get_user_content', params=params)
        metadata = php_ini_settings['result']['metadata']['LangPHP']
        self.format_title(metadata['vhost'] + " (" + metadata['path'] + ")")
        print(self.unescape(php_ini_settings['result']['data']['content']))

    def ini_set(self):
        user_domains = self.breakup_domains_by_users()
        for domain, user in user_domains.iteritems():
                self.ini_setter(user, domain)

    def ini_setter(self,user,domain):
        params = ['type=vhost', 'vhost=' + domain]
        for index, setting in enumerate(self.args.setting, start=1):
            params.append("directive-" + str(index) + "=" + setting[0] + "%3A" + setting[1])
        self.call('uapi', user=user, 
            module='LangPHP', cmd='php_ini_set_user_basic_directives', 
            params=params)
        i = 2
        while i < len(params):
            params[i] = params[i].split('=')
            params[i] = params[i][1]
            i += 1
        dir_string = ', '.join(params[2:]).replace('%3A', ' = ')
        logger.log('info', "Set php-ini directives:  %s :: for domain %s", dir_string, domain)

    def ini_edit(self):
        user_domains = self.breakup_domains_by_users()
        for domain, user in user_domains.iteritems():
            self.ini_editor(user, domain)
        for domain, user in user_domains.iteritems():
            self.ini_getter(user, domain)

    def ini_editor(self, user, domain):
        params = ['type=vhost', 'vhost=' + domain]
        php_ini_settings = self.call('uapi', user=user, module='LangPHP', cmd='php_ini_get_user_content', params=params)
        contents_to_edit = tempfile.NamedTemporaryFile(prefix=domain + '-', suffix=".tmp",)
        contents_to_edit.write(self.unescape(php_ini_settings['result']['data']['content']))
        contents_to_edit.flush()
        call([os.environ.get('EDITOR', 'nano'), contents_to_edit.name])
        contents_to_edit.seek(0)
        uri_encoded_contents = urllib.quote(contents_to_edit.read(), safe='')
        setparams = params
        setparams.append('content=' + uri_encoded_contents)
        self.call('uapi', user=user, module='LangPHP', cmd='php_ini_set_user_content', params=setparams)
        logger.log('info', 'PHP.INI saved for doamin :: %s', domain)


    
