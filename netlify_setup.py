"""Create an EMPTY Netlify project, or reuse its ID. No files are deployed."""
import argparse, getpass, json, os, re
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote

def request(path,token,payload=None):
    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
    req=Request('https://api.netlify.com/api/v1/'+path,headers=headers,
                data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urlopen(req,timeout=40) as response: return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f'Netlify HTTP {exc.code}: check permissions, plan and name availability. No alternate name selected.') from None
    except (URLError,TimeoutError):
        raise RuntimeError('Network error. Re-run: existing sites are checked before creating.') from None

def setup(name,token,create=False,team=None):
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',name):
        raise RuntimeError('Use a lowercase Netlify project name, max 63 characters')
    # Paginate all accessible sites; a repeated command never blindly creates again.
    matches=[]; page=1
    while True:
        items=request(f'sites?per_page=100&page={page}',token)
        if not isinstance(items,list): raise RuntimeError('Unexpected Netlify site response')
        matches.extend(s for s in items if s.get('name')==name and (team is None or s.get('account_slug')==team))
        if len(items)<100: break
        page+=1
    if len(matches)>1: raise RuntimeError('Ambiguous project; specify --team')
    if matches: result=matches[0]
    else:
        if not create: raise RuntimeError('Project absent. Use --create to create the empty project without uploading files.')
        if team is None:
            accounts=request('accounts',token)
            if not isinstance(accounts,list) or len(accounts)!=1:
                raise RuntimeError('Specify your Netlify team slug with --team; multiple or no teams returned')
            team=accounts[0]['slug']
        result=request(quote(team,safe='')+'/sites',token,{'name':name})
    if result.get('name')!=name or not result.get('id'):
        raise RuntimeError('Netlify did not confirm the requested name/ID; inspect dashboard')
    print('Project name:',result['name'])
    print('NETLIFY_SITE_ID='+result['id'])
    print('No site files uploaded by this command. Paste the ID into GitHub Actions Secrets.')
    return result['id']

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--name',default='global-bollinger-eodhd')
    p.add_argument('--create',action='store_true'); p.add_argument('--team')
    args=p.parse_args()
    token=os.getenv('NETLIFY_AUTH_TOKEN') or getpass.getpass('Netlify token (hidden): ')
    try: setup(args.name,token,args.create,args.team)
    except RuntimeError as exc: raise SystemExit(str(exc)) from None
