import boto3
import logging
from botocore.exceptions import ClientError
import json
import time
import psycopg2

logger = logging.getLogger(__name__)

def create_security_group_for_rds(myregion):
    ec2 = boto3.client('ec2', region_name=myregion)

    response = ec2.describe_vpcs()
    vpc_id = response.get('Vpcs', [{}])[0].get('VpcId', '')

    try:
        response = ec2.create_security_group(GroupName='w6pg1_rds_sg',
                                            Description='Security Group for RDS',
                                            VpcId=vpc_id)
        security_group_id = response['GroupId']
        print('Security Group Created %s in vpc %s.' % (security_group_id, vpc_id))

        data = ec2.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=[
                {'IpProtocol': 'tcp',
                'FromPort': 5432,
                'ToPort': 5432,
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
            ])
        print('Ingress Successfully Set %s' % data)
        return security_group_id
    except ClientError as e:
        print(e)
        

def create_rds(username, password, sg_id, myregion):
    db_identifier = 'w6pg1-rds'
    rds = boto3.client('rds', region_name=myregion)

    try:
        rds.create_db_instance(DBInstanceIdentifier=db_identifier,
                               AllocatedStorage=20,
                               DBName='blog',
                               Engine='postgres',
                               # General purpose SSD
                               StorageType='gp2',
                               StorageEncrypted=True,
                               AutoMinorVersionUpgrade=True,
                               # Set this to true later?
                               MultiAZ=False,
                               MasterUsername=username,
                               MasterUserPassword=password,
                               VpcSecurityGroupIds=[sg_id],
                               DBInstanceClass='db.t3.micro')
                               #Tags=[{'Key': 'MyTag', 'Value': 'Hawaii'}])
        print ("Starting RDS instance with ID: %s" % db_identifier)
    except ClientError as e:
        if 'DBInstanceAlreadyExists' in e.message:
            print ('DB instance %s exists already, continuing to poll ...' % db_identifier)
    finally:

        running = True
        while running:
            response = rds.describe_db_instances(DBInstanceIdentifier=db_identifier)

            db_instances = response['DBInstances']
            if len(db_instances) != 1:
                raise Exception('Whoa cowboy! More than one DB instance returned; this should never happen')

            db_instance = db_instances[0]

            status = db_instance['DBInstanceStatus']

            print ('Last DB status: %s' % status)

            time.sleep(10)
            if status == 'available':
                endpoint = db_instance['Endpoint']
                host = endpoint['Address']
                print ('DB instance ready with host: %s' % host)
                running = False
        return host


def create_secret(username, password, host, myregion):
    """
    Creates a new secret. The secret value can be a string or bytes.

    :param name: The name of the secret to create.
    :param secret_value: The value of the secret.
    :return: Metadata about the newly created secret.
    """
    client = boto3.client("secretsmanager", region_name=myregion)
    name = "w6pg1_rds-secret"

    try:
        response = client.create_secret(Name = name,
                                        SecretString = '{"username":"%s","password":"%s","engine":"postgres","host":"%s","port":"5432","dbname":"blog","dbInstanceIdentifier":"w6pg1-rds"}' % (username, password, host))
        
        logger.info("Created secret %s.", name)
    except ClientError:
        logger.exception("Couldn't get secret %s.", name)
        raise
    else:
        return True

def get_secret_value(name, myregion):
        client = boto3.client("secretsmanager", region_name=myregion)

        try:
            kwargs = {'SecretId': name}
            response = client.get_secret_value(**kwargs)
            logger.info("Got value for secret %s.", name)
        except ClientError:
            logger.exception("Couldn't get value for secret %s.", name)
            raise
        else:
            return json.loads(response['SecretString'])

def get_db_connection(myregion):
    data = get_secret_value("w6pg1_rds-secret", myregion)
    conn = psycopg2.connect("host=%s dbname=%s port=%s user=%s password=%s" % (data['host'], data['dbname'], data['port'], data['username'], data['password']))
    return conn

def create_posts_table(myregion):
    try:
        connection = get_db_connection(myregion)
        cur = connection.cursor()
        try:
            cur.execute("""
            CREATE TABLE posts (
            id SERIAL PRIMARY KEY,
            created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            title TEXT NOT NULL,
            content TEXT NOT NULL);
            """)
        except:
            print("No working command")
        connection.commit()
        connection.close()
        return True
    except:
        return False

def add_default_topics_to_db(myregion):
    try:
        connection = get_db_connection(myregion)
        cur = connection.cursor()

        cur.execute("INSERT INTO posts (title, content) VALUES (%s, %s)",
                    ('J??m??hditk??? Tee kuten Heidi ja muuta urasi suuntaa', 'Jokaisen maanantain ei tarvitse olla nousukiitoa, mutta jos perjantaihin menness?? ei sorvin ????ress?? ole juuri ilon tai innostumisen kokemuksia irronnut, ollaan l??hell?? j??m??ht??mist??. Oireet on helppo tunnistaa ja hoito on jokaisen ulottuvilla ??? uranvaihto ei katso taustaa eik?? vaadi vuosien opiskelua.')
                    )

        cur.execute("INSERT INTO posts (title, content) VALUES (%s, %s)",
                    ('Tradenomista IT-ammattilaiseksi: Ilkan tarina', """Kansainv??lisen kaupan tradenomiksi valmistunut ja useita vuosia ty??uraa LVI-alalla rakentanut Ilkka Jokela hypp??si Academyn kiihdytyskaistalle saatuaan kipin??n koodiin.

    ???Olin jo p????tt??nyt, ett?? haluan koodata ja kouluttautua IT-alalle. Hain ja p????sinkin yliopistoon lukemaan tietotekniikkaa. Huomasin kuitenkin Academyn, joten en ottanut opiskelupaikkaa vastaan. Olen aina ollut kiinnostunut teknologiasta ja haluan tehd?? jotain, mik?? on t??t?? p??iv???????, Ilkka avaa omaa polkuaan.

    Muiden academylaisten tyyliin my??s Ilkalle halu ja kyky oppia uutta on luontaista. Ilkka painottaakin, ett?? ???uuden oppiminen on upeaa, ja varsinkin se fiilis, kun on ihan pihalla. Se samanaikaisesti sek?? turhauttaa ett?? antaa nautintoa, koska tiet???? ett?? nyt oppii varmasti jotakin uutta.???

    Ilkka muistelee j??nnitt??neens?? Academyn intensiivist?? pr??ssi?? enemm??n kuin oli syyt??. 12 viikkoa meni nopeasti ja uusia oppeja tuli ennalta-arvaamaton m????r??. Koulutuksen paras anti meni kuitenkin pelkk???? tietoa syvemm??lle.

    ???Parasta Academyssa oli ehdottomasti porukan yhteishenki sek?? mahtavat opettajat. K??teen koulutuksesta j??i ennen kaikkea tieto siit??, ett?? mit?? vain voi oppia, kun on halu oppia.???""")
                    )

        cur.execute("INSERT INTO posts (title, content) VALUES (%s, %s)",
                    ('T??t?? haluat kysy?? AW Academysta ja uranvaihdosta', """Uudenlaisen koulutusmallin saapuminen Suomeen on her??tt??nyt vuosien varrella keskustelua ja kirvoittanut kysymyksi??. Kokosimme t??h??n blogikirjoitukseen muutamia verkkokeskusteluissa (mm. Helsingin Sanomat, Taloussanomat) esiintyneit?? kysymyksi?? ja vastauksia.""")
                    )

        cur.execute("INSERT INTO posts (title, content) VALUES (%s, %s)",
                    ('Kaiken takana on koodi ??? ja sen voi oppia 12 viikossa', """Miten koodi py??ritt???? maailmaa? Ja miten sen oppiminen 12 viikon intensiivikoulutuksessa on mahdollista? IT-konsulttina ja -kouluttajana ty??skentelev?? Tommi Ter??svirta kertoo.

    Tietokoneet ja niiden k??ytt??m?? kieli on muuttanut maailmaamme k??sitt??m??tt??m??n paljon kohtuullisen pieness?? ajassa. Jos kuka tahansa saisi kyydin aikakoneella 30 vuoden takaa nykyp??iv????n, j??isi aikamatkustajan suu taatusti auki monessa arkisessa kohtaamisessa 2019-luvun alkuasukkaan kanssa.

    Koodi on yksi k??ytetyimmist?? ja arkemme kannalta vaikuttavimmista kielist??. Sen osaamisesta on pelk??st????n hy??ty?? ja sen osaajille on ty??markkinoilla jatkuvaa tilausta.

    Academyn 12 viikon ja vakituisen ty??paikan Academic Workin asiakasyrityksen palveluksessa takaavan koodauskoulutusohjelman opettaja Tommi Ter??svirta Sovellolta osaa avata t??m??n kiehtovan kielen sek?? sen oppimisen saloja syvemmin.""")
                    )

        connection.commit()
        connection.close()
        return True
    except:
        return False
    



if __name__ == "__main__":
    pass